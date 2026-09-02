from __future__ import annotations

from dataclasses import dataclass, asdict
from math import sqrt


def _fixture_rows(row: dict, gw: int) -> list[dict]:
    return [f for f in row.get("fixtures", []) if int(f.get("gw") or -1) == int(gw)]


def appearance_probability(row: dict, gw: int) -> float:
    fixtures = _fixture_rows(row, gw)
    if fixtures:
        zero = 1.0
        seen = False
        for f in fixtures:
            p = (f.get("projection") or {}).get("p_appearance")
            if p is None:
                p = (f.get("minutes_projection") or {}).get("p_appearance")
            if p is None:
                continue
            seen = True
            zero *= 1.0 - max(0.0, min(1.0, float(p)))
        if seen:
            return max(0.0, min(1.0, 1.0-zero))
    mp = row.get("minutes_projection") or {}
    if mp.get("p_appearance") is not None:
        return max(0.0, min(1.0, float(mp["p_appearance"])))
    return max(0.0, min(1.0, float(row.get("expected_minutes") or 0.0)/65.0))


def gw_distribution(row: dict, gw: int) -> dict:
    fixtures = _fixture_rows(row, gw)
    mean = float(row.get("per_gw", {}).get(gw, 0.0))
    if fixtures:
        variance = sum(float((f.get("projection") or {}).get("variance") or 0.0) for f in fixtures)
        p10 = sum(float((f.get("projection") or {}).get("p10") or 0.0) for f in fixtures)
        p90 = sum(float((f.get("projection") or {}).get("p90") or 0.0) for f in fixtures)
        p10plus_components = [float((f.get("projection") or {}).get("p_10_plus") or 0.0) for f in fixtures]
        p10plus = 1.0
        for p in p10plus_components:
            p10plus *= 1.0-max(0.0, min(1.0, p))
        p10plus = 1.0-p10plus
        pret_components = [float((f.get("projection") or {}).get("p_return") or 0.0) for f in fixtures]
        p_return = 1.0
        for p in pret_components:
            p_return *= 1.0-max(0.0, min(1.0, p))
        p_return = 1.0-p_return
    else:
        variance = max(1.0, 1.8*mean)
        sd = sqrt(variance)
        p10 = max(0.0, mean-1.2816*sd)
        p90 = mean+1.2816*sd
        p10plus = max(0.0, min(1.0, mean/18.0))
        p_return = max(0.0, min(1.0, mean/10.0))
    return {
        "mean": mean,
        "variance": max(0.0, variance),
        "sd": sqrt(max(0.0, variance)),
        "p10": p10,
        "p90": p90,
        "p_10_plus": max(0.0, min(1.0, p10plus)),
        "p_return": max(0.0, min(1.0, p_return)),
        "p_appearance": appearance_probability(row, gw),
        "p_zero": 1.0-appearance_probability(row, gw),
    }


@dataclass(frozen=True)
class CaptaincyCandidate:
    player_id: int
    mean: float
    p10: float
    p90: float
    variance: float
    p_10_plus: float
    p_return: float
    attacking_rate: float
    p_appearance: float
    p_zero: float
    utility: float

    def as_dict(self):
        return asdict(self)


def candidate(row: dict, gw: int, *, downside_penalty: float = 0.08, upside_bonus: float = 0.03,
              haul_bonus: float = 0.35, return_bonus: float = 0.20, attacking_rate_bonus: float = 0.15) -> CaptaincyCandidate:
    d = gw_distribution(row, gw)
    attacking_rate = max(0.0, float(row.get("xg90") or 0.0) + float(row.get("xa90") or 0.0))
    # Expected points stays dominant. Captaincy gets only a bounded preference
    # for genuine attacking/haul upside because the armband doubles that upside.
    utility = d["mean"] - downside_penalty*d["sd"] + upside_bonus*max(0.0, d["p90"]-d["mean"])
    utility += haul_bonus*d["p_10_plus"] + return_bonus*d["p_return"] + attacking_rate_bonus*min(1.5, attacking_rate)
    # Zero-minute risk is already in mean EP; this is a small tie-break only.
    utility -= 0.20*d["p_zero"]
    return CaptaincyCandidate(
        player_id=int(row["player_id"]), mean=round(d["mean"], 4), p10=round(d["p10"], 4),
        p90=round(d["p90"], 4), variance=round(d["variance"], 4), p_10_plus=round(d["p_10_plus"], 4),
        p_return=round(d["p_return"], 4), attacking_rate=round(attacking_rate, 4),
        p_appearance=round(d["p_appearance"], 4), p_zero=round(d["p_zero"], 4), utility=round(utility, 4),
    )


def captain_pair_value(cap: CaptaincyCandidate, vice: CaptaincyCandidate, *, triple_captain: bool = False) -> float:
    # Use calibrated captain utility for ranking, with vice value only when the
    # captain records zero minutes. Expected-extra-points is reported separately.
    multiplier = 2 if triple_captain else 1
    return multiplier*(cap.utility + cap.p_zero*vice.utility)

def captain_pair_expected_points(cap: CaptaincyCandidate, vice: CaptaincyCandidate, *, triple_captain: bool = False) -> float:
    multiplier = 2 if triple_captain else 1
    return multiplier*(cap.mean + cap.p_zero*vice.mean)


def recommend_captaincy(
    starter_ids,
    proj_by_id: dict,
    gw: int,
    *,
    triple_captain: bool = False,
    downside_penalty: float = 0.08,
    upside_bonus: float = 0.03,
    prefer_attackers: bool = True,
    defender_override_margin: float = 1.25,
):
    ids = [int(x) for x in starter_ids]
    candidates = {pid: candidate(proj_by_id[pid], gw, downside_penalty=downside_penalty, upside_bonus=upside_bonus) for pid in ids}
    pairs = []
    for cap_id in ids:
        cap = candidates[cap_id]
        for vice_id in ids:
            if vice_id == cap_id:
                continue
            vice = candidates[vice_id]
            value = captain_pair_value(cap, vice, triple_captain=triple_captain)
            # Keep the existing safety philosophy without hard-banning a truly
            # exceptional defender/GK projection.
            if prefer_attackers and int(proj_by_id[cap_id]["position"]) in {1, 2}:
                best_attack_utility = max(
                    (candidates[x].utility for x in ids if int(proj_by_id[x]["position"]) in {3, 4}),
                    default=-999.0,
                )
                if cap.utility < best_attack_utility + defender_override_margin:
                    value -= 2.0
            pairs.append((value, cap.utility, vice.utility, cap_id, vice_id))
    if not pairs:
        raise ValueError("Captaincy requires at least two starters")
    pairs.sort(reverse=True)
    value, _, _, cap_id, vice_id = pairs[0]
    ranking = sorted(candidates.values(), key=lambda c: c.utility, reverse=True)

    # The engine optimises the captain/vice PAIR, not captain utility alone.
    # Expose a pair-consistent ranking so reports never claim that a lower
    # individual-utility captain outranks a higher one without showing why.
    best_by_captain = {}
    for pair_value, cap_utility, vice_utility, candidate_cap, candidate_vice in pairs:
        if candidate_cap not in best_by_captain:
            best_by_captain[candidate_cap] = {
                "captain": candidate_cap,
                "best_vice": candidate_vice,
                "pair_value": round(pair_value, 4),
                "captain_utility": round(cap_utility, 4),
                "vice_utility": round(vice_utility, 4),
            }
    pair_ranking = sorted(best_by_captain.values(), key=lambda x: x["pair_value"], reverse=True)
    return {
        "captain": cap_id,
        "vice_captain": vice_id,
        "expected_extra_points": round(captain_pair_expected_points(candidates[cap_id], candidates[vice_id], triple_captain=triple_captain), 3),
        "pair_value": round(value, 3),
        "candidates": [x.as_dict() for x in ranking],
        "captain_pair_rankings": pair_ranking,
    }
