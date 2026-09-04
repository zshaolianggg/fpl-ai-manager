from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from math import exp
import re


@dataclass(frozen=True)
class TeamStrength:
    team_id: int
    attack_home: float = 1.0
    attack_away: float = 1.0
    defence_home: float = 1.0
    defence_away: float = 1.0


@dataclass(frozen=True)
class FixtureExpectation:
    home_xg: float
    away_xg: float
    home_cs_probability: float
    away_cs_probability: float


def _positive(value, default=1.0):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fpl_label_strengths(team_rows: list[dict]) -> dict[int, TeamStrength]:
    """Normalize official FPL attack/defence strength fields around league average.

    FPL strength fields are relative ratings, not xG. We use them only as a
    stable team-strength prior and convert the matchup to expected goals below.
    Missing fields degrade to a neutral 1.0 rating.
    """
    rows = list(team_rows or [])
    if not rows:
        return {}

    fields = (
        "strength_attack_home", "strength_attack_away",
        "strength_defence_home", "strength_defence_away",
    )
    means = {}
    for field in fields:
        vals = [_positive(r.get(field), 0.0) for r in rows]
        vals = [v for v in vals if v > 0]
        means[field] = sum(vals) / len(vals) if vals else 1.0

    out = {}
    for row in rows:
        tid = int(row["id"])
        out[tid] = TeamStrength(
            team_id=tid,
            attack_home=_positive(row.get("strength_attack_home")) / means["strength_attack_home"],
            attack_away=_positive(row.get("strength_attack_away")) / means["strength_attack_away"],
            # Higher FPL defence strength means a better defence, so the ratio
            # remains >1 for stronger teams and is inverted in the matchup.
            defence_home=_positive(row.get("strength_defence_home")) / means["strength_defence_home"],
            defence_away=_positive(row.get("strength_defence_away")) / means["strength_defence_away"],
        )
    return out


_GENERIC_TEAM_WORDS = {
    "fc", "afc", "united", "city", "town", "albion", "athletic",
    "wanderers", "hotspur", "forest", "rovers", "county", "and", "the",
}


def _team_tokens(name: str) -> set[str]:
    cleaned = re.sub(r"[&/]", " ", (name or "").lower())
    cleaned = re.sub(r"[^a-z0-9\s]", "", cleaned)
    words = [w for w in cleaned.split() if w]
    distinctive = {w for w in words if w not in _GENERIC_TEAM_WORDS}
    return distinctive or set(words)


def match_understat_teams(team_rows: list[dict], understat_teams: dict) -> dict[str, int]:
    """Map Understat team ids to FPL team ids by distinctive-word name overlap.

    A closed 20-team set makes fuzzy matching safe as long as an unmatched team
    is left out rather than guessed: a wrong pairing would silently corrupt
    that team's strength rating, which is worse than falling back to the FPL
    label prior for that one team.
    """
    fpl_tokens = {int(row["id"]): _team_tokens(row.get("name")) for row in (team_rows or [])}
    out = {}
    for uid, team in (understat_teams or {}).items():
        u_tokens = _team_tokens((team or {}).get("title"))
        best_id, best_overlap = None, 0
        for fid, tokens in fpl_tokens.items():
            overlap = len(u_tokens & tokens)
            if overlap > best_overlap:
                best_id, best_overlap = fid, overlap
        if best_id is not None and best_overlap > 0:
            out[str(uid)] = best_id
    return out


def _parse_understat_date(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            continue
    return None


def _match_weight(days_ago, half_life_days):
    if days_ago is None or days_ago < 0:
        return 0.0
    return 0.5 ** (days_ago / max(1.0, half_life_days))


def _team_rating_from_history(history, side, now, half_life_days):
    """Recency-weighted (day-based exponential decay) xG/xGA for one side.

    Concatenating current- and prior-season match rows and decaying by actual
    calendar days lets old matches fade out naturally as the new season
    accumulates data, instead of needing a separate season-boundary rule.
    """
    xg_w = xga_w = total_w = 0.0
    for m in history or []:
        if (m or {}).get("h_a") != side:
            continue
        dt = _parse_understat_date(m.get("date"))
        days_ago = (now - dt).total_seconds()/86400.0 if dt else 60.0
        w = _match_weight(days_ago, half_life_days)
        if w <= 0:
            continue
        xg_w += w*_num(m.get("xG"))
        xga_w += w*_num(m.get("xGA"))
        total_w += w
    if total_w <= 0:
        return None
    return xg_w/total_w, xga_w/total_w, total_w


def _understat_side_ratings(matched, understat_current, understat_prior, side, now, half_life_days):
    """Per matched FPL team id: (xg_rate, xga_rate, effective_weight) or None."""
    out = {}
    for uid, fid in matched.items():
        current_hist = ((understat_current or {}).get(uid) or {}).get("history", [])
        prior_hist = ((understat_prior or {}).get(uid) or {}).get("history", [])
        rating = _team_rating_from_history(list(prior_hist)+list(current_hist), side, now, half_life_days)
        if rating:
            out[fid] = rating
    return out


def _blend_understat_strengths(fpl_strengths, team_rows, understat_current, understat_prior, *,
                                half_life_days, prior_pseudo_weight, now):
    understat_teams = understat_current or understat_prior or {}
    matched = match_understat_teams(team_rows, understat_teams)
    # Below this many matched teams, per-side league averages would be too
    # noisy to trust; keep the FPL-label prior untouched instead of guessing.
    if len(matched) < 10:
        return fpl_strengths

    home = _understat_side_ratings(matched, understat_current, understat_prior, "h", now, half_life_days)
    away = _understat_side_ratings(matched, understat_current, understat_prior, "a", now, half_life_days)
    if not home or not away:
        return fpl_strengths

    league_home_xg = sum(v[0] for v in home.values())/len(home)
    league_home_xga = sum(v[1] for v in home.values())/len(home)
    league_away_xg = sum(v[0] for v in away.values())/len(away)
    league_away_xga = sum(v[1] for v in away.values())/len(away)
    if min(league_home_xg, league_home_xga, league_away_xg, league_away_xga) <= 0:
        return fpl_strengths

    out = {}
    for tid, anchor in fpl_strengths.items():
        attack_home, defence_home = anchor.attack_home, anchor.defence_home
        attack_away, defence_away = anchor.attack_away, anchor.defence_away
        if tid in home:
            xg, xga, weight = home[tid]
            shrink = weight/(weight+prior_pseudo_weight)
            attack_home = shrink*(xg/league_home_xg) + (1-shrink)*anchor.attack_home
            defence_home = shrink*(league_home_xga/max(0.05, xga)) + (1-shrink)*anchor.defence_home
        if tid in away:
            xg, xga, weight = away[tid]
            shrink = weight/(weight+prior_pseudo_weight)
            attack_away = shrink*(xg/league_away_xg) + (1-shrink)*anchor.attack_away
            defence_away = shrink*(league_away_xga/max(0.05, xga)) + (1-shrink)*anchor.defence_away
        out[tid] = TeamStrength(
            team_id=tid, attack_home=attack_home, attack_away=attack_away,
            defence_home=defence_home, defence_away=defence_away,
        )
    return out


def build_team_strengths(
    team_rows: list[dict] | None,
    understat_current: dict | None = None,
    understat_prior: dict | None = None,
    *,
    half_life_days: float = 200.0,
    prior_pseudo_weight: float = 6.0,
    now=None,
) -> dict[int, TeamStrength]:
    """Team attack/defence strength, blending FPL's own labels with observed
    Understat match-level xG/xGA when available.

    FPL's strength fields are coarse and updated infrequently; recency-weighted
    Understat team xG/xGA is a data-driven correction. Understat data is
    optional and shrunk toward the FPL-label prior when a team has little
    recent match history (new promotion, early season, or provider failure),
    so this always degrades gracefully to the previous FPL-only behavior.
    """
    fpl_strengths = _fpl_label_strengths(team_rows)
    if not understat_current and not understat_prior:
        return fpl_strengths
    try:
        now = now or datetime.now(timezone.utc).replace(tzinfo=None)
        return _blend_understat_strengths(
            fpl_strengths, team_rows, understat_current, understat_prior,
            half_life_days=half_life_days, prior_pseudo_weight=prior_pseudo_weight, now=now,
        )
    except Exception:
        return fpl_strengths


def fixture_expectation(
    home_team_id: int,
    away_team_id: int,
    strengths: dict[int, TeamStrength],
    league_home_xg: float = 1.55,
    league_away_xg: float = 1.25,
) -> FixtureExpectation:
    home = strengths.get(int(home_team_id), TeamStrength(int(home_team_id)))
    away = strengths.get(int(away_team_id), TeamStrength(int(away_team_id)))

    home_xg = league_home_xg * home.attack_home / max(0.55, away.defence_away)
    away_xg = league_away_xg * away.attack_away / max(0.55, home.defence_home)

    # Guard against extreme official ratings early in a season.
    home_xg = max(0.20, min(3.80, home_xg))
    away_xg = max(0.15, min(3.50, away_xg))
    return FixtureExpectation(
        home_xg=home_xg,
        away_xg=away_xg,
        home_cs_probability=exp(-away_xg),
        away_cs_probability=exp(-home_xg),
    )
