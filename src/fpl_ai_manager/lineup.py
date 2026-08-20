
from __future__ import annotations
from itertools import combinations

def best_lineup(squad_ids, proj_by_id, gw, bench_weight=.2, bench_boost=False, triple_captain=False):
    groups={1:[],2:[],3:[],4:[]}
    for pid in squad_ids:
        r=proj_by_id[pid]
        groups[r["position"]].append((pid,float(r["per_gw"].get(gw,0))))
    for pos in groups: groups[pos].sort(key=lambda x:x[1], reverse=True)
    if not groups[1]: raise ValueError("No goalkeeper")
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
            captain=max(starters,key=lambda x:x[1])
            vice=max([x for x in starters if x[0]!=captain[0]],key=lambda x:x[1])
            mult=2 if triple_captain else 1
            score=sum(x[1] for x in starters)+mult*captain[1]
            score += (1.0 if bench_boost else bench_weight)*sum(x[1] for x in bench)
            cand={"starters":[x[0] for x in starters],"bench":[x[0] for x in bench],
                  "captain":captain[0],"vice_captain":vice[0],"score":round(score,2),
                  "bench_points":round(sum(x[1] for x in bench),2)}
            if best is None or cand["score"]>best["score"]: best=cand
    if best is None: raise ValueError("No legal starting formation")
    return best
