
from __future__ import annotations

CONFIDENCE_FACTOR = {"HIGH": 1.00, "MEDIUM": 0.96, "LOW": 0.88}

def robust_points(row, gw):
    raw = float(row["per_gw"].get(gw, 0))
    return raw * CONFIDENCE_FACTOR.get(row.get("confidence","LOW"), 0.88)

def _captain(starters, proj_by_id, gw):
    """Balanced-risk captaincy.
    MID/FWD is the default captain pool. A GK/DEF may captain only when its
    robust projection materially beats the best attacking option.
    """
    ranked = sorted(starters, key=lambda x: robust_points(proj_by_id[x[0]], gw), reverse=True)
    attackers = [x for x in ranked if proj_by_id[x[0]]["position"] in {3,4}
                 and proj_by_id[x[0]].get("expected_minutes",0) >= 65]
    best_attack = attackers[0] if attackers else ranked[0]
    top = ranked[0]
    if proj_by_id[top[0]]["position"] in {1,2}:
        conf = proj_by_id[top[0]].get("confidence","LOW")
        margin = 2.5 if conf == "LOW" else 1.5
        if robust_points(proj_by_id[top[0]],gw) < robust_points(proj_by_id[best_attack[0]],gw) + margin:
            top = best_attack
    vice = next(x for x in ranked if x[0] != top[0])
    return top, vice

def best_lineup(squad_ids, proj_by_id, gw, bench_weight=.2, bench_boost=False, triple_captain=False):
    groups={1:[],2:[],3:[],4:[]}
    for pid in squad_ids:
        r=proj_by_id[pid]
        groups[r["position"]].append((pid, robust_points(r,gw)))
    for pos in groups:
        groups[pos].sort(key=lambda x:x[1], reverse=True)
    if not groups[1]:
        raise ValueError("No goalkeeper")
    gk=groups[1][0]
    best=None
    for d in range(3,6):
        for m in range(2,6):
            f=10-d-m
            if f<1 or f>3: continue
            if d>len(groups[2]) or m>len(groups[3]) or f>len(groups[4]): continue
            starters=[gk]+groups[2][:d]+groups[3][:m]+groups[4][:f]
            ids={x[0] for x in starters}
            bench=[x for pos in (1,2,3,4) for x in groups[pos] if x[0] not in ids]
            captain, vice = _captain(starters, proj_by_id, gw)
            mult=2 if triple_captain else 1
            # Raw report score remains point-estimate based; lineup choice is robust.
            raw_start = sum(float(proj_by_id[x[0]]["per_gw"].get(gw,0)) for x in starters)
            raw_bench = sum(float(proj_by_id[x[0]]["per_gw"].get(gw,0)) for x in bench)
            raw_cap = float(proj_by_id[captain[0]]["per_gw"].get(gw,0))
            score=raw_start + mult*raw_cap + (1.0 if bench_boost else bench_weight)*raw_bench
            robust_score = sum(x[1] for x in starters) + mult*robust_points(proj_by_id[captain[0]],gw)
            robust_score += (1.0 if bench_boost else bench_weight)*sum(x[1] for x in bench)
            cand={"starters":[x[0] for x in starters],"bench":[x[0] for x in bench],
                  "captain":captain[0],"vice_captain":vice[0],"score":round(score,2),
                  "robust_score":round(robust_score,2),"bench_points":round(raw_bench,2)}
            if best is None or cand["robust_score"]>best["robust_score"]:
                best=cand
    if best is None:
        raise ValueError("No legal starting formation")
    return best
