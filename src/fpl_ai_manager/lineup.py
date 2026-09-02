from __future__ import annotations

from itertools import permutations
from math import prod

from .captaincy import recommend_captaincy

CONFIDENCE_FACTOR = {"HIGH": 1.00, "MEDIUM": 0.96, "LOW": 0.88}


def robust_points(row, gw):
    raw = float(row["per_gw"].get(gw, 0))
    return raw * CONFIDENCE_FACTOR.get(row.get("confidence", "LOW"), 0.88)


def _ownership(row):
    try:
        return float(row.get("selected_by_percent") or 0)
    except (TypeError, ValueError):
        return 0.0


def _fixture_rows(row, gw):
    return [f for f in row.get("fixtures", []) if int(f.get("gw") or -1) == int(gw)]


def gw_appearance_probability(row, gw):
    """Probability of recording any minutes in a GW.

    For a double gameweek, the player only scores zero appearance minutes if
    they miss every fixture. Fixture appearance probabilities are treated as
    independent here; V3.4 calibration can replace that approximation later.
    """
    fixtures = _fixture_rows(row, gw)
    if fixtures:
        zero = 1.0
        for f in fixtures:
            p = (f.get("projection") or {}).get("p_appearance")
            if p is None:
                p = (f.get("minutes_projection") or {}).get("p_appearance")
            if p is None:
                continue
            zero *= max(0.0, min(1.0, 1.0 - float(p)))
        return max(0.0, min(1.0, 1.0-zero))

    mp = row.get("minutes_projection") or {}
    if mp.get("p_appearance") is not None:
        return max(0.0, min(1.0, float(mp["p_appearance"])))
    em = float(row.get("expected_minutes") or 0)
    return max(0.0, min(1.0, em/65.0))


def gw_zero_probability(row, gw):
    return 1.0 - gw_appearance_probability(row, gw)


def _captain(starters, proj_by_id, gw):
    ranked = sorted(starters, key=lambda x: robust_points(proj_by_id[x[0]], gw), reverse=True)
    attackers = [x for x in ranked if proj_by_id[x[0]]["position"] in {3, 4}
                 and proj_by_id[x[0]].get("expected_minutes", 0) >= 65]
    best_attack = attackers[0] if attackers else ranked[0]
    top = ranked[0]
    if proj_by_id[top[0]]["position"] in {1, 2}:
        conf = proj_by_id[top[0]].get("confidence", "LOW")
        margin = 2.5 if conf == "LOW" else 1.5
        if robust_points(proj_by_id[top[0]], gw) < robust_points(proj_by_id[best_attack[0]], gw) + margin:
            top = best_attack
    premium_attackers = [x for x in attackers if proj_by_id[x[0]].get("price", 0) >= 120]
    if premium_attackers:
        eo_anchor = max(premium_attackers, key=lambda x: _ownership(proj_by_id[x[0]]))
        anchor_row = proj_by_id[eo_anchor[0]]
        if anchor_row.get("confidence", "LOW") == "LOW":
            edge = robust_points(proj_by_id[top[0]], gw) - robust_points(anchor_row, gw)
            if edge < 1.25:
                top = eo_anchor
    remaining_attackers = [x for x in attackers if x[0] != top[0]]
    vice = remaining_attackers[0] if remaining_attackers else next(x for x in ranked if x[0] != top[0])
    return top, vice


def _poisson_binomial(probs):
    """Distribution for the number of independent events occurring."""
    dist = [1.0]
    for p in probs:
        p = max(0.0, min(1.0, float(p)))
        nxt = [0.0] * (len(dist)+1)
        for k, val in enumerate(dist):
            nxt[k] += val*(1-p)
            nxt[k+1] += val*p
        dist = nxt
    return dist


def _prob_more_starter_misses_than_prior_bench_apps(starter_miss_probs, prior_bench_app_probs):
    """P(M > A), where M is starter no-shows and A prior bench appearances.

    This is the event that the next bench player is still required. It captures
    both multiple starter absences and a preceding substitute failing to appear.
    Formation legality is handled conservatively when bench order is chosen.
    """
    miss_dist = _poisson_binomial(starter_miss_probs)
    app_dist = _poisson_binomial(prior_bench_app_probs)
    total = 0.0
    for misses, pm in enumerate(miss_dist):
        for apps, pa in enumerate(app_dist):
            if misses > apps:
                total += pm*pa
    return max(0.0, min(1.0, total))


def _formation_counts(starters, proj_by_id):
    counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for pid, _ in starters:
        counts[int(proj_by_id[pid]["position"])] += 1
    return counts


def _bench_legality_factor(bench_pid, starters, proj_by_id, gw):
    """Probability-weighted first-order formation legality.

    Older builds averaged legality equally across all ten outfield starters.
    That can over/under-value a bench player when the actual no-show risk is
    concentrated in one position. Alpha 5 weights each possible missing starter
    by that starter's own GW no-show probability.
    """
    bpos = int(proj_by_id[bench_pid]["position"])
    counts = _formation_counts(starters, proj_by_id)
    eligible_weight = 0.0
    total_weight = 0.0
    for pid, _ in starters:
        spos = int(proj_by_id[pid]["position"])
        if spos == 1:
            continue
        miss = gw_zero_probability(proj_by_id[pid], gw)
        if miss <= 0:
            continue
        total_weight += miss
        trial = dict(counts)
        trial[spos] -= 1
        trial[bpos] += 1
        if trial[2] >= 3 and trial[3] >= 2 and trial[4] >= 1:
            eligible_weight += miss
    return eligible_weight/max(1e-9, total_weight) if total_weight > 0 else 1.0


def gw_points_conditional_on_appearance(row, gw):
    """Expected GW points conditional on recording minutes.

    ``per_gw`` is already an *unconditional* expectation (zero-minute outcomes
    are included by the projection engine). Keeping this helper explicit lets
    auto-sub valuation correctly use P(appearance) * E[points | appearance]
    without accidentally applying P(appearance) twice.
    """
    p_app = gw_appearance_probability(row, gw)
    ep = float(row.get("per_gw", {}).get(gw, 0))
    if p_app <= 1e-9:
        return 0.0
    return ep/p_app


def expected_auto_sub_points(starters, bench_order, proj_by_id, gw):
    """Approximate expected points added by FPL automatic substitutions.

    The method is probabilistic rather than a fixed bench weight: it combines
    starter no-show probabilities, ordered bench availability, and a bounded
    formation-legality factor. Goalkeepers are handled separately.
    """
    starter_gk = next((pid for pid, _ in starters if proj_by_id[pid]["position"] == 1), None)
    bench_gk = next((pid for pid in bench_order if proj_by_id[pid]["position"] == 1), None)
    total = 0.0
    if starter_gk is not None and bench_gk is not None:
        total += gw_zero_probability(proj_by_id[starter_gk], gw) * float(proj_by_id[bench_gk]["per_gw"].get(gw, 0))

    outfield_starters = [(pid, pts) for pid, pts in starters if proj_by_id[pid]["position"] != 1]
    outfield_bench = [pid for pid in bench_order if proj_by_id[pid]["position"] != 1]
    miss_probs = [gw_zero_probability(proj_by_id[pid], gw) for pid, _ in outfield_starters]
    prior_apps = []
    for pid in outfield_bench:
        needed = _prob_more_starter_misses_than_prior_bench_apps(miss_probs, prior_apps)
        legality = _bench_legality_factor(pid, starters, proj_by_id, gw)
        p_app = gw_appearance_probability(proj_by_id[pid], gw)
        conditional_ep = gw_points_conditional_on_appearance(proj_by_id[pid], gw)
        total += needed * legality * p_app * conditional_ep
        prior_apps.append(p_app)
    return round(total, 4)


def _best_bench_order(bench, starters, proj_by_id, gw):
    gks = [x[0] for x in bench if proj_by_id[x[0]]["position"] == 1]
    out = [x[0] for x in bench if proj_by_id[x[0]]["position"] != 1]
    if len(out) <= 1:
        return gks + out
    best_order = None
    best_value = -1.0
    for perm in permutations(out):
        order = gks + list(perm)
        value = expected_auto_sub_points(starters, order, proj_by_id, gw)
        if value > best_value:
            best_value, best_order = value, order
    return best_order


def best_lineup(
    squad_ids,
    proj_by_id,
    gw,
    bench_weight=.2,
    bench_boost=False,
    triple_captain=False,
    selection_mode="robust",
):
    groups = {1: [], 2: [], 3: [], 4: []}
    for pid in squad_ids:
        r = proj_by_id[pid]
        groups[r["position"]].append((pid, robust_points(r, gw)))
    for pos in groups:
        groups[pos].sort(key=lambda x: x[1], reverse=True)
    if not groups[1]:
        raise ValueError("No goalkeeper")
    gk = groups[1][0]
    best = None
    for d in range(3, 6):
        for m in range(2, 6):
            f = 10-d-m
            if f < 1 or f > 3:
                continue
            if d > len(groups[2]) or m > len(groups[3]) or f > len(groups[4]):
                continue
            starters = [gk]+groups[2][:d]+groups[3][:m]+groups[4][:f]
            ids = {x[0] for x in starters}
            bench = [x for pos in (1, 2, 3, 4) for x in groups[pos] if x[0] not in ids]
            bench_order = _best_bench_order(bench, starters, proj_by_id, gw)
            if selection_mode == "probabilistic":
                cap_rec = recommend_captaincy([x[0] for x in starters], proj_by_id, gw, triple_captain=triple_captain)
                captain = next(x for x in starters if x[0] == cap_rec["captain"])
                vice = next(x for x in starters if x[0] == cap_rec["vice_captain"])
            else:
                cap_rec = None
                captain, vice = _captain(starters, proj_by_id, gw)
            cap_extra_multiplier = 2 if triple_captain else 1

            raw_start = sum(float(proj_by_id[x[0]]["per_gw"].get(gw, 0)) for x in starters)
            raw_bench = sum(float(proj_by_id[x[0]]["per_gw"].get(gw, 0)) for x in bench)
            raw_cap = float(proj_by_id[captain[0]]["per_gw"].get(gw, 0))
            score = raw_start + cap_extra_multiplier*raw_cap + (1.0 if bench_boost else bench_weight)*raw_bench

            robust_score = sum(x[1] for x in starters) + cap_extra_multiplier*robust_points(proj_by_id[captain[0]], gw)
            robust_score += (1.0 if bench_boost else bench_weight)*sum(x[1] for x in bench)

            cap_zero = gw_zero_probability(proj_by_id[captain[0]], gw)
            vice_ep = float(proj_by_id[vice[0]]["per_gw"].get(gw, 0))
            captain_extra = cap_extra_multiplier*(raw_cap + cap_zero*vice_ep)
            if bench_boost:
                auto_sub = 0.0
                probabilistic_score = raw_start + raw_bench + captain_extra
            else:
                auto_sub = expected_auto_sub_points(starters, bench_order, proj_by_id, gw)
                probabilistic_score = raw_start + auto_sub + captain_extra

            cand = {
                "starters": [x[0] for x in starters],
                "bench": bench_order,
                "captain": captain[0],
                "vice_captain": vice[0],
                "score": round(score, 2),
                "robust_score": round(robust_score, 2),
                "probabilistic_score": round(probabilistic_score, 2),
                "expected_auto_sub_points": round(auto_sub, 2),
                "captain_fallback_points": round(captain_extra-cap_extra_multiplier*raw_cap, 2),
                "captaincy_model": cap_rec,
                "bench_points": round(raw_bench, 2),
            }
            key = "probabilistic_score" if selection_mode == "probabilistic" else "robust_score"
            if best is None or cand[key] > best[key]:
                best = cand
    if best is None:
        raise ValueError("No legal starting formation")
    return best
