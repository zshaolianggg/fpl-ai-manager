from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime
from math import exp, factorial, sqrt
from .stats import norm_name
from .minutes import project_minutes, MinutesProjection
from .rules import rules_for_season, ScoringRules
from .team_model import build_team_strengths, fixture_expectation, FixtureExpectation
from .set_pieces import infer_set_piece_role, penalty_goals_current_season

PRIOR_XG90 = {1:0.01,2:0.05,3:0.18,4:0.32}
PRIOR_XA90 = {1:0.01,2:0.08,3:0.16,4:0.12}

# Historical attacking observations are converted to a neutral-fixture basis
# before future matchup strength is applied. Keep this correction deliberately
# bounded: early-season team ratings are useful priors, not precise truth.
HIST_ATTACK_MULT_MIN = 0.80
HIST_ATTACK_MULT_MAX = 1.20
NEUTRAL_ATTACK_XG = 1.35


def _num(x, default=0.0):
    try: return float(x)
    except (TypeError, ValueError): return default


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def fixture_map(fixtures, teams, next_gw, horizon=8):
    out = defaultdict(list)
    for f in fixtures:
        ev = f.get("event")
        if not ev or not (next_gw <= int(ev) < next_gw+horizon):
            continue
        h,a = int(f["team_h"]),int(f["team_a"])
        common = {
            "gw": int(ev), "kickoff_time": f.get("kickoff_time"),
            "home_team": h, "away_team": a,
        }
        out[h].append({**common,"opponent":a,"opponent_name":teams[a],"venue":"H","difficulty":int(f.get("team_h_difficulty") or 3)})
        out[a].append({**common,"opponent":h,"opponent_name":teams[h],"venue":"A","difficulty":int(f.get("team_a_difficulty") or 3)})
    for team_id in out:
        out[team_id].sort(key=lambda x: (x["gw"], x.get("kickoff_time") or ""))
    return out


def _understat_rates(row, pos):
    if not row:
        return PRIOR_XG90[pos], PRIOR_XA90[pos], 0.0
    mins = _num(row.get("time"))
    if mins <= 0:
        return PRIOR_XG90[pos], PRIOR_XA90[pos], 0.0
    return 90*_num(row.get("xG"))/mins, 90*_num(row.get("xA"))/mins, mins


def _historical_attack_multiplier(team_id, opponent_team, was_home, strengths):
    """Expected attacking environment for one already-played fixture.

    The same shrunk team/matchup model used for future fixtures is used here,
    but the historical correction is capped more tightly (0.80-1.20). This
    avoids overreacting to noisy early-season FPL strength ratings.
    """
    if not strengths or not team_id or not opponent_team:
        return 1.0
    try:
        team_id = int(team_id)
        opponent_team = int(opponent_team)
    except (TypeError, ValueError):
        return 1.0
    if bool(was_home):
        fx = fixture_expectation(team_id, opponent_team, strengths)
        own_xg = fx.home_xg
    else:
        fx = fixture_expectation(opponent_team, team_id, strengths)
        own_xg = fx.away_xg
    shrunk = 0.5 + 0.5*(own_xg/NEUTRAL_ATTACK_XG)
    return max(HIST_ATTACK_MULT_MIN, min(HIST_ATTACK_MULT_MAX, shrunk))


def _normalized_fpl_history_rates(history, pos, team_id, strengths):
    """Return neutral-fixture xG/xA rates from current-season match rows.

    Each played match is divided by its bounded attacking-environment
    multiplier. A minute-weighted exposure factor is also returned so the
    current-season Understat aggregate can receive the same schedule correction
    without fetching hundreds of extra player-match pages.
    """
    mins_total = raw_xg = raw_xa = norm_xg = norm_xa = 0.0
    exposure_weighted = 0.0
    usable = 0
    for row in list(history or []):
        mins = _num(row.get("minutes"))
        if mins <= 0:
            continue
        has_xg = "expected_goals" in row or "xG" in row
        has_xa = "expected_assists" in row or "xA" in row
        if not (has_xg or has_xa):
            continue
        xg = _num(row.get("expected_goals", row.get("xG")))
        xa = _num(row.get("expected_assists", row.get("xA")))
        mult = _historical_attack_multiplier(
            team_id, row.get("opponent_team"), row.get("was_home"), strengths
        )
        mins_total += mins
        raw_xg += xg
        raw_xa += xa
        norm_xg += xg/max(0.01, mult)
        norm_xa += xa/max(0.01, mult)
        exposure_weighted += mins/max(0.01, mult)
        usable += 1
    if mins_total <= 0 or usable <= 0:
        return None
    return {
        "raw_xg90": 90*raw_xg/mins_total,
        "raw_xa90": 90*raw_xa/mins_total,
        "normalized_xg90": 90*norm_xg/mins_total,
        "normalized_xa90": 90*norm_xa/mins_total,
        "exposure_factor": exposure_weighted/mins_total,
        "minutes": mins_total,
        "matches": usable,
    }


def attacking_rates(
    player, ext_current, ext_prior, *, history=None, strengths=None,
    team_id=None, penalty_confirmed=False, return_diagnostics=False
):
    pos = int(player["element_type"])
    key = norm_name(player.get("web_name"))
    cur = ext_current.get(key)
    prior = ext_prior.get(key)
    cxg,cxa,cmins = _understat_rates(cur,pos)
    pxg,pxa,pmins = _understat_rates(prior,pos)
    fmins = _num(player.get("minutes"))
    if fmins > 0:
        raw_fxg = 90*_num(player.get("expected_goals"))/fmins
        raw_fxa = 90*_num(player.get("expected_assists"))/fmins
    else:
        raw_fxg,raw_fxa = PRIOR_XG90[pos],PRIOR_XA90[pos]

    hist = _normalized_fpl_history_rates(
        history, pos, team_id or player.get("team"), strengths
    )
    if hist:
        # Prefer the match-level FPL rate because it lets us normalize the exact
        # fixtures in which the player appeared. Apply the minute-weighted same
        # schedule correction to Understat's current aggregate before blending.
        fxg = hist["normalized_xg90"]
        fxa = hist["normalized_xa90"]
        exposure = max(HIST_ATTACK_MULT_MIN, min(HIST_ATTACK_MULT_MAX, hist["exposure_factor"]))
        adj_cxg = cxg*exposure
        adj_cxa = cxa*exposure
        normalization_method = "match_level_fpl_plus_understat_exposure"
    else:
        fxg, fxa = raw_fxg, raw_fxa
        adj_cxg, adj_cxa = cxg, cxa
        exposure = 1.0
        normalization_method = "aggregate_fallback"

    current_weight = min(0.80, max(fmins,cmins)/900.0)
    if penalty_confirmed:
        # A confirmed current-season penalty conversion is strong, low-variance
        # evidence of the current role; do not let a thin-minutes sample get
        # diluted back toward a generic prior that predates the penalty duty.
        current_weight = max(current_weight, 0.55)
    live_xg = (fxg + adj_cxg)/2 if cmins else fxg
    live_xa = (fxa + adj_cxa)/2 if cmins else fxa
    # Prior-season Understat is league-aggregate data. A full EPL season has a
    # near-balanced schedule, so we retain it as the stabilizing prior rather
    # than pretending we have match-level opponent context that we do not have.
    prior_xg = pxg if pmins else PRIOR_XG90[pos]
    prior_xa = pxa if pmins else PRIOR_XA90[pos]
    xg90 = current_weight*live_xg + (1-current_weight)*prior_xg
    xa90 = current_weight*live_xa + (1-current_weight)*prior_xa
    conf = "MEDIUM" if current_weight >= .35 else "LOW"
    diagnostics = {
        "method": normalization_method,
        "historical_schedule_adjusted": bool(hist),
        "matches_adjusted": int(hist["matches"]) if hist else 0,
        "minutes_adjusted": round(hist["minutes"], 1) if hist else 0.0,
        "understat_current_exposure_factor": round(exposure, 3),
        "raw_fpl_xg90": round(raw_fxg, 3),
        "raw_fpl_xa90": round(raw_fxa, 3),
        "normalized_fpl_xg90": round(fxg, 3),
        "normalized_fpl_xa90": round(fxa, 3),
        "prior_season_normalization": "aggregate_prior_retained",
        "penalty_taker_confirmed_current_season": bool(penalty_confirmed),
    }
    result = (max(0,xg90), max(0,xa90), conf)
    return (*result, diagnostics) if return_diagnostics else result


@dataclass(frozen=True)
class FixtureProjection:
    mean_points: float
    appearance_points: float
    goal_points: float
    assist_points: float
    clean_sheet_points: float
    save_points: float
    defensive_contribution_points: float
    bonus_points: float
    conceded_points: float
    expected_minutes: float
    p_start: float
    p_appearance: float
    p_60_plus: float
    p_blank: float
    p_return: float
    p_10_plus: float
    variance: float
    p10: float
    p50: float
    p90: float

    def as_dict(self):
        return asdict(self)


def _poisson_tail(lam: float, threshold: int) -> float:
    if threshold <= 0:
        return 1.0
    if lam <= 0:
        return 0.0
    # Thresholds are small (10/12), so direct summation is stable here.
    below = sum(exp(-lam) * (lam**k) / factorial(k) for k in range(threshold))
    return max(0.0, min(1.0, 1.0-below))


def defensive_action_rate90(history: list[dict], position: int) -> float:
    total_actions = 0.0
    total_minutes = 0.0
    for row in list(history or [])[-8:]:
        mins = _num(row.get("minutes"))
        if mins <= 0:
            continue
        cbi = _num(row.get("clearances_blocks_interceptions"))
        tackles = _num(row.get("tackles"))
        recoveries = _num(row.get("recoveries")) if position in {3,4} else 0.0
        raw = cbi + tackles + recoveries
        # Some FPL responses expose only the already-combined field.
        if raw <= 0:
            raw = _num(row.get("defensive_contribution"))
        total_actions += raw
        total_minutes += mins
    return 90.0*total_actions/total_minutes if total_minutes > 0 else 0.0


def expected_defensive_contribution_points(
    history: list[dict], position: int, minutes_projection: MinutesProjection, rules: ScoringRules
) -> float:
    threshold = rules.defensive_contribution_thresholds.get(position)
    if threshold is None:
        return 0.0
    rate90 = defensive_action_rate90(history, position)
    lam = rate90 * minutes_projection.expected_minutes / 90.0
    return rules.defensive_contribution_points * _poisson_tail(lam, threshold)


def _fixture_minutes(player, history, prior, news_index, fixture, previous_fixture):
    congestion_days = None
    cur_dt = _parse_dt(fixture.get("kickoff_time"))
    prev_dt = _parse_dt((previous_fixture or {}).get("kickoff_time"))
    if cur_dt and prev_dt:
        congestion_days = max(0.0, (cur_dt-prev_dt).total_seconds()/86400.0)
    return project_minutes(player, history, prior, news_index, congestion_days=congestion_days)


def _team_fixture_for_player(f, strengths):
    fx = fixture_expectation(f["home_team"], f["away_team"], strengths)
    if f["venue"] == "H":
        return fx.home_xg, fx.away_xg, fx.home_cs_probability, fx
    return fx.away_xg, fx.home_xg, fx.away_cs_probability, fx


def project_fixture(
    player: dict,
    minutes_projection: MinutesProjection | float,
    xg90: float,
    xa90: float,
    f: dict,
    *,
    history: list[dict] | None = None,
    team_expectation: FixtureExpectation | None = None,
    scoring_rules: ScoringRules | None = None,
    strengths: dict | None = None,
) -> FixtureProjection:
    """Project one fixture while retaining a V3 component breakdown.

    A numeric minutes value is accepted for compatibility with older callers.
    """
    rules = scoring_rules or rules_for_season("2026/27")
    if isinstance(minutes_projection, (int, float)):
        em = max(0.0, min(90.0, float(minutes_projection)))
        p_app = min(1.0, em/30.0)
        p60 = max(0.0,min(1.0,(em-25)/40))
        mp = MinutesProjection(em, min(.99,em/90), p60, p_app, 1-p_app, max(60,em), 16, .5, ())
    else:
        mp = minutes_projection

    pos = int(player["element_type"])
    if strengths is not None:
        own_xg, opp_xg, cs_prob, fx = _team_fixture_for_player(f, strengths)
    elif team_expectation is not None:
        fx = team_expectation
        if f["venue"] == "H":
            own_xg, opp_xg, cs_prob = fx.home_xg, fx.away_xg, fx.home_cs_probability
        else:
            own_xg, opp_xg, cs_prob = fx.away_xg, fx.home_xg, fx.away_cs_probability
    else:
        # Neutral fallback only. FDR is deliberately no longer converted into a
        # hard-coded attack/clean-sheet lookup table.
        own_xg, opp_xg, cs_prob = (1.45 if f["venue"] == "H" else 1.20), (1.20 if f["venue"] == "H" else 1.45), exp(-(1.20 if f["venue"] == "H" else 1.45))

    mins_ratio = mp.expected_minutes/90.0
    # Scale individual historic rates by matchup attacking environment relative
    # to a neutral 1.35 xG baseline, with shrinkage to avoid extreme swings.
    attack_mult = max(.70, min(1.35, 0.5 + 0.5*(own_xg/1.35)))
    appearance = mp.p_appearance + mp.p_60_plus
    goals = xg90*mins_ratio*attack_mult*rules.goal_points[pos]
    assists = xa90*mins_ratio*attack_mult*rules.assist_points
    cs = cs_prob * rules.clean_sheet_points[pos] * mp.p_60_plus

    saves = 0.0
    if pos == 1 and _num(player.get("minutes")) > 0:
        saves90 = 90*_num(player.get("saves"))/_num(player.get("minutes"))
        saves = (saves90/rules.save_threshold)*mins_ratio*rules.save_points

    dc = expected_defensive_contribution_points(history or [], pos, mp, rules)

    bonus_rate = 0.0
    if _num(player.get("minutes")) > 0:
        # Current-season bonus is useful but noisy; shrink rather than extrapolate
        # at full historical rate under the revised 2026/27 BPS environment.
        raw_bonus90 = 90*_num(player.get("bonus"))/_num(player.get("minutes"))
        bonus_rate = min(.65, .70*raw_bonus90)
    bonus = bonus_rate*mins_ratio

    # Expected -1 for each pair of goals conceded by GK/DEF. Approximate with
    # expected opponent goals and require a plausible 60+ minute appearance.
    conceded = -(opp_xg/2.0) * mp.p_60_plus if pos in {1,2} else 0.0
    mean = max(0.0, appearance+goals+assists+cs+saves+dc+bonus+conceded)

    return_mean = xg90*mins_ratio*attack_mult + xa90*mins_ratio*attack_mult
    p_return = 1-exp(-max(0.0, return_mean))
    p_blank = max(0.0, min(1.0, 1-p_return))
    # Lightweight uncertainty envelope. V3.4 backtesting will calibrate these.
    variance = max(1.0, 1.8*mean + 8.0*p_return*(1-p_return) + 6.0*mp.p_zero_minutes)
    sd = sqrt(variance)
    p10 = max(0.0, mean-1.2816*sd)
    p90 = mean+1.2816*sd
    p10_plus = max(0.0, min(1.0, (mean/10.0)*0.35 + p_return*0.35))

    return FixtureProjection(
        mean_points=round(mean,3), appearance_points=round(appearance,3),
        goal_points=round(goals,3), assist_points=round(assists,3),
        clean_sheet_points=round(cs,3), save_points=round(saves,3),
        defensive_contribution_points=round(dc,3), bonus_points=round(bonus,3),
        conceded_points=round(conceded,3), expected_minutes=mp.expected_minutes,
        p_start=mp.p_start, p_appearance=mp.p_appearance, p_60_plus=mp.p_60_plus,
        p_blank=round(p_blank,4), p_return=round(p_return,4), p_10_plus=round(p10_plus,4),
        variance=round(variance,3), p10=round(p10,3), p50=round(mean,3), p90=round(p90,3),
    )


def _team_penalty_goals(players, understat_current):
    """Aggregate current-season penalty goals by team for share estimation."""
    out = {}
    for p in players:
        goals = penalty_goals_current_season(p, understat_current or {})
        if goals <= 0:
            continue
        tid = int(p.get("team") or 0)
        out[tid] = out.get(tid, 0.0)+goals
    return out


def build_projections(
    players, teams, fixtures, next_gw, summaries, external, news_index, horizon=8,
    team_rows=None, season="2026/27", team_strength_cfg=None
):
    fmap = fixture_map(fixtures, teams, next_gw, horizon)
    rules = rules_for_season(season)
    ts_cfg = team_strength_cfg or {}
    strengths = build_team_strengths(
        team_rows, external.get("current_teams"), external.get("prior_teams"),
        half_life_days=float(ts_cfg.get("understat_half_life_days", 200.0)),
        prior_pseudo_weight=float(ts_cfg.get("understat_prior_pseudo_weight", 6.0)),
    )
    team_pens = _team_penalty_goals(players, external.get("current", {}))
    rows=[]
    for p in players:
        pid=int(p["id"])
        hist=(summaries.get(pid) or {}).get("history",[])
        prior=external.get("prior",{}).get(norm_name(p.get("web_name")))
        base_mp = project_minutes(p,hist,prior,news_index)
        set_piece_role = infer_set_piece_role(p,external.get("current",{}),team_pens)
        xg90,xa90,rate_conf,rate_diag=attacking_rates(
            p,external.get("current",{}),external.get("prior",{}),
            history=hist,strengths=strengths,team_id=int(p["team"]),
            penalty_confirmed=set_piece_role.is_penalty_taker,return_diagnostics=True
        )
        per={}
        fixture_detail=[]
        team_fixtures=fmap.get(int(p["team"]),[])
        previous=None
        fixture_mps=[]
        for gw in range(next_gw,next_gw+horizon):
            pts=0.0
            for f in [x for x in team_fixtures if x["gw"]==gw]:
                mp=_fixture_minutes(p,hist,prior,news_index,f,previous)
                fp=project_fixture(p,mp,xg90,xa90,f,history=hist,scoring_rules=rules,strengths=strengths)
                pts += fp.mean_points
                fixture_mps.append(mp)
                fixture_detail.append({**f,"projected_points":round(fp.mean_points,2),"minutes_projection":mp.as_dict(),"projection":fp.as_dict()})
                previous=f
            per[gw]=round(pts,2)
        def total(n): return round(sum(per.get(g,0) for g in range(next_gw,next_gw+n)),2)
        avg_min = round(sum(x.expected_minutes for x in fixture_mps)/len(fixture_mps),1) if fixture_mps else base_mp.expected_minutes
        conf_score = min(base_mp.confidence, .68 if rate_conf=="MEDIUM" else .45)
        conf = "HIGH" if conf_score>=.75 else ("MEDIUM" if conf_score>=.5 else "LOW")
        rows.append({
            "player_id":pid,"player":p.get("web_name"),"team_id":int(p["team"]),"team":teams[int(p["team"])],
            "position":int(p["element_type"]),"price":int(p["now_cost"]),
            # Compatibility fields consumed by V2 optimizer/chips.
            "expected_minutes":avg_min,"xg90":round(xg90,3),"xa90":round(xa90,3),"confidence":conf,
            "gw1":total(1),"gw3":total(3),"gw6":total(6),"gw8":total(8),"per_gw":per,
            # V3-rich evidence.
            "minutes_projection":base_mp.as_dict(),"projection_confidence":round(conf_score,3),
            "set_piece_role":asdict(set_piece_role),"scoring_season":rules.season,
            "attacking_rate_normalization":rate_diag,
            "fixtures":fixture_detail,"status":p.get("status"),"selected_by_percent":p.get("selected_by_percent")
        })
    return rows


def weighted_player_score(row, weights):
    return round(weights["gw1"]*row["gw1"] + weights["gw3"]*row["gw3"] + weights["gw6"]*row["gw6"],4)
