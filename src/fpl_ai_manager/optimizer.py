
from __future__ import annotations
from dataclasses import dataclass
from itertools import combinations
from collections import Counter
import csv, io, hashlib, json
import pulp
from .lineup import best_lineup, robust_points
from .validator import validate_squad, validate_plan

def _pid(plan): 
    raw=json.dumps({"t":plan.get("transfers",[]),"c":plan.get("chip"),"s":sorted(plan.get("squad_ids",[]))},sort_keys=True)
    return hashlib.sha1(raw.encode()).hexdigest()[:10]

def plan_metrics(squad_ids, proj_by_id, next_gw, weights, bench_weight, chip=None):
    per={}
    lineups={}
    for i in range(8):
        gw=next_gw+i
        lu=best_lineup(squad_ids,proj_by_id,gw,bench_weight,
                       bench_boost=(chip=="bboost" and i==0),
                       triple_captain=(chip=="3xc" and i==0))
        per[gw]=lu["score"]; lineups[gw]=lu
    h1=per[next_gw]
    h3=sum(per[next_gw+i] for i in range(3))
    h6=sum(per[next_gw+i] for i in range(6))
    h8=sum(per[next_gw+i] for i in range(8))
    weighted=weights["gw1"]*h1+weights["gw3"]*h3+weights["gw6"]*h6
    return {"gw1":round(h1,2),"gw3":round(h3,2),"gw6":round(h6,2),"gw8":round(h8,2),
            "weighted":round(weighted,2),"lineups":lineups}

def flexibility_adjustment(squad_ids, proj_by_id, bank_after, cap=2.0):
    # Tie-breaker only: a little cash plus usable bench/minutes, capped by design.
    usable=sum(proj_by_id[p]["expected_minutes"]>=60 for p in squad_ids)
    price_tiers=len({proj_by_id[p]["price"]//10 for p in squad_ids})
    raw=0.15*min(bank_after/10,4)+0.08*max(0,usable-11)+0.04*price_tiers
    return round(min(cap,raw),2)

def legal_after_transfer(squad_ids, players_by_id):
    return not validate_squad(squad_ids,players_by_id)

def _purchase_budget(state):
    return int(state["bank"])+sum(int(x["selling_price"]) for x in state["squad"])

def _ilp_squads(players, proj_by_id, budget, weights, top_n=20, min_minutes_players=13, utility_override=None):
    prob=pulp.LpProblem("fpl_squad",pulp.LpMaximize)
    ids=[int(p["id"]) for p in players if int(p["id"]) in proj_by_id and p.get("status") not in {"u"}]
    x={pid:pulp.LpVariable(f"x_{pid}",cat="Binary") for pid in ids}
    util={pid:(utility_override(pid) if utility_override else weights["gw1"]*proj_by_id[pid]["gw1"]+weights["gw3"]*proj_by_id[pid]["gw3"]+weights["gw6"]*proj_by_id[pid]["gw6"]) for pid in ids}
    prob += pulp.lpSum(util[p]*x[p] for p in ids)
    prob += pulp.lpSum(x.values())==15
    for pos,count in {1:2,2:5,3:5,4:3}.items():
        prob += pulp.lpSum(x[p] for p in ids if proj_by_id[p]["position"]==pos)==count
    clubs={int(p["team"]) for p in players}
    for club in clubs:
        prob += pulp.lpSum(x[p] for p in ids if proj_by_id[p]["team_id"]==club)<=3
    prob += pulp.lpSum(proj_by_id[p]["price"]*x[p] for p in ids)<=budget
    prob += pulp.lpSum(x[p] for p in ids if proj_by_id[p]["expected_minutes"]>=60)>=min_minutes_players
    solver=pulp.PULP_CBC_CMD(msg=False)
    found=[]
    for _ in range(top_n):
        status=prob.solve(solver)
        if pulp.LpStatus[status]!="Optimal": break
        squad=[p for p in ids if x[p].value() and x[p].value()>.5]
        found.append(squad)
        prob += pulp.lpSum(x[p] for p in squad)<=14
    return found



def _gw1_market_prior(row):
    try:
        own=float(row.get("selected_by_percent") or 0)
    except (TypeError,ValueError):
        own=0.0
    price=float(row.get("price") or 0)
    pos=int(row.get("position") or 0)
    if pos not in {3,4}:
        return min(0.6, max(0.0, own-25)/50.0)
    ownership_component=max(0.0,own-25.0)/15.0
    premium_component=max(0.0,price-95.0)/40.0
    return min(4.0, ownership_component+premium_component)

def _gw1_ilp_squads(players, proj_by_id, budget, weights, bench_weight, top_n=30):
    """Optimize the actual GW1 decision: 15-man squad + legal XI + captain.
    Bench is valued at only the agreed 20%, so this cannot silently build a
    Bench-Boost-shaped squad.
    """
    prob=pulp.LpProblem("fpl_gw1_squad",pulp.LpMaximize)
    ids=[int(p["id"]) for p in players if int(p["id"]) in proj_by_id and p.get("status") not in {"u","i","s"}]
    x={pid:pulp.LpVariable(f"x_{pid}",cat="Binary") for pid in ids}
    y={pid:pulp.LpVariable(f"y_{pid}",cat="Binary") for pid in ids}
    c={pid:pulp.LpVariable(f"c_{pid}",cat="Binary") for pid in ids}

    util={}
    cap_util={}
    for pid in ids:
        r=proj_by_id[pid]
        conf={"HIGH":1.0,"MEDIUM":0.96,"LOW":0.88}.get(r.get("confidence","LOW"),0.88)
        util[pid]=conf*(weights["gw1"]*r["gw1"]+weights["gw3"]*r["gw3"]+weights["gw6"]*r["gw6"])
        if r.get("confidence","LOW")=="LOW":
            util[pid] += _gw1_market_prior(r)
        cap_util[pid]=robust_points(r,1)

    # x contributes discounted bench value; y upgrades selected players from
    # bench-value to starter-value. Captain adds one extra GW1 score.
    prob += (
        pulp.lpSum(bench_weight*util[p]*x[p] + (1-bench_weight)*util[p]*y[p] for p in ids)
        + pulp.lpSum(cap_util[p]*c[p] for p in ids)
    )
    prob += pulp.lpSum(x.values())==15
    prob += pulp.lpSum(y.values())==11
    prob += pulp.lpSum(c.values())==1
    for p in ids:
        prob += y[p] <= x[p]
        prob += c[p] <= y[p]

    for pos,count in {1:2,2:5,3:5,4:3}.items():
        prob += pulp.lpSum(x[p] for p in ids if proj_by_id[p]["position"]==pos)==count
    prob += pulp.lpSum(y[p] for p in ids if proj_by_id[p]["position"]==1)==1
    prob += pulp.lpSum(y[p] for p in ids if proj_by_id[p]["position"]==2)>=3
    prob += pulp.lpSum(y[p] for p in ids if proj_by_id[p]["position"]==2)<=5
    prob += pulp.lpSum(y[p] for p in ids if proj_by_id[p]["position"]==3)>=2
    prob += pulp.lpSum(y[p] for p in ids if proj_by_id[p]["position"]==3)<=5
    prob += pulp.lpSum(y[p] for p in ids if proj_by_id[p]["position"]==4)>=1
    prob += pulp.lpSum(y[p] for p in ids if proj_by_id[p]["position"]==4)<=3

    clubs={proj_by_id[p]["team_id"] for p in ids}
    for club in clubs:
        prob += pulp.lpSum(x[p] for p in ids if proj_by_id[p]["team_id"]==club)<=3
    prob += pulp.lpSum(proj_by_id[p]["price"]*x[p] for p in ids)<=budget
    prob += pulp.lpSum(x[p] for p in ids if proj_by_id[p]["expected_minutes"]>=60)>=13

    # Balanced-risk initial structure: at least one high-price attacking
    # captaincy anchor, without hard-coding any player by name.
    anchors=[p for p in ids if proj_by_id[p]["position"] in {3,4} and proj_by_id[p]["price"]>=100
             and proj_by_id[p]["expected_minutes"]>=65]
    if anchors:
        prob += pulp.lpSum(x[p] for p in anchors)>=1
    eo_anchors=[p for p in ids if proj_by_id[p]["position"] in {3,4}
                and proj_by_id[p]["price"]>=120
                and float(proj_by_id[p].get("selected_by_percent") or 0)>=60
                and proj_by_id[p]["expected_minutes"]>=65]
    if eo_anchors:
        prob += pulp.lpSum(x[p] for p in eo_anchors)>=1

    solver=pulp.PULP_CBC_CMD(msg=False)
    found=[]
    for _ in range(top_n):
        if pulp.LpStatus[prob.solve(solver)]!="Optimal": break
        squad=[p for p in ids if x[p].value() and x[p].value()>.5]
        found.append(squad)
        prob += pulp.lpSum(x[p] for p in squad)<=14
    return found

def initial_build_plans(players, players_by_id, proj_by_id, next_gw, cfg):
    weights=cfg["projection_weights"]; bench=cfg["bench_weight"]
    squads=_gw1_ilp_squads(players,proj_by_id,1000,weights,bench,max(35,cfg["optimizer"]["top_plans"]))
    plans=[]
    for squad in squads:
        spend=sum(proj_by_id[p]["price"] for p in squad)
        met=plan_metrics(squad,proj_by_id,next_gw,weights,bench)
        bank=1000-spend
        # Keeping a little bank is useful; hoarding >£1.0m in GW1 is a mild
        # structural cost because it sacrifices starting-XI power.
        excess_bank_penalty=max(0,(bank-10)/5)*0.35
        flex=max(0, flexibility_adjustment(squad,proj_by_id,bank,cfg["flexibility_cap_points"])-excess_bank_penalty)
        robust_weighted=(
            weights["gw1"]*met["lineups"][next_gw]["robust_score"]
            + weights["gw3"]*sum(met["lineups"][next_gw+i]["robust_score"] for i in range(3))
            + weights["gw6"]*sum(met["lineups"][next_gw+i]["robust_score"] for i in range(6))
        )
        plan={"transfers":[],"squad_ids":squad,"bank_after":bank,"hit_cost":0,"chip":None,
              "metrics":met,"flexibility_adjustment":round(flex,2),
              "optimizer_score":round(robust_weighted+flex,2),"lineup":met["lineups"][next_gw],
              "reason_flags":["GW1 XI-first optimization","bench weighted 20%","uncertainty-discounted"]}
        plan["plan_id"]=_pid(plan)
        if not validate_plan(plan,players_by_id,proj_by_id):
            plans.append(plan)
    plans.sort(key=lambda p:p["optimizer_score"],reverse=True)
    return diversify(plans,cfg["optimizer"]["top_plans"])

def diversify(plans,n):
    out=[]
    for p in plans:
        sig=set(p["squad_ids"])
        if all(len(sig ^ set(q["squad_ids"]))>=2 or p.get("chip")!=q.get("chip") for q in out):
            out.append(p)
        if len(out)>=n: break
    return out

def _candidate_ids(projections,current_ids,cfg):
    out=[]
    for pos in (1,2,3,4):
        g=[r for r in projections if r["position"]==pos and r["player_id"] not in current_ids and r["status"] not in {"i","s","u"}]
        g.sort(key=lambda r:(r["gw6"],r["gw3"],r["gw1"]),reverse=True)
        out += [r["player_id"] for r in g[:cfg["optimizer"]["candidate_per_position"]]]
    return out

def managed_plans(state, players_by_id, projections, proj_by_id, next_gw, cfg):
    weights=cfg["projection_weights"]; bench=cfg["bench_weight"]; ft=int(state["free_transfers"])
    current=[int(x["player_id"]) for x in state["squad"]]
    sell={int(x["player_id"]):int(x["selling_price"]) for x in state["squad"]}
    candidates=_candidate_ids(projections,set(current),cfg)
    base_met=plan_metrics(current,proj_by_id,next_gw,weights,bench)
    base_robust=weights["gw1"]*base_met["lineups"][next_gw]["robust_score"]+weights["gw3"]*sum(base_met["lineups"][next_gw+i]["robust_score"] for i in range(3))+weights["gw6"]*sum(base_met["lineups"][next_gw+i]["robust_score"] for i in range(6))
    base={"transfers":[],"squad_ids":current,"bank_after":int(state["bank"]),"hit_cost":0,"chip":None,
          "metrics":base_met,"flexibility_adjustment":flexibility_adjustment(current,proj_by_id,int(state["bank"]),cfg["flexibility_cap_points"]),
          "optimizer_score":round(base_robust,2),"lineup":base_met["lineups"][next_gw],
          "reason_flags":["ROLL"]}
    base["plan_id"]=_pid(base)
    frontier=[base]; all_plans=[base]
    max_t=min(cfg["optimizer"]["max_transfers_considered"],ft+2)
    for depth in range(1,max_t+1):
        expanded=[]
        for parent in frontier:
            used_out={t["out"] for t in parent["transfers"]}
            owned=set(parent["squad_ids"])
            for out in [p for p in current if p not in used_out]:
                pos=proj_by_id[out]["position"]
                for inn in candidates:
                    if inn in owned or proj_by_id[inn]["position"]!=pos: continue
                    bank=parent["bank_after"]+sell[out]-proj_by_id[inn]["price"]
                    if bank<0: continue
                    squad=[p for p in parent["squad_ids"] if p!=out]+[inn]
                    if not legal_after_transfer(squad,players_by_id): continue
                    transfers=parent["transfers"]+[{"out":out,"in":inn,"sell":sell[out],"buy":proj_by_id[inn]["price"]}]
                    met=plan_metrics(squad,proj_by_id,next_gw,weights,bench)
                    gross=met["weighted"]-base_met["weighted"]
                    hit=max(0,depth-ft)*4
                    structural=(proj_by_id[out]["expected_minutes"]<45 or met["gw6"]-base_met["gw6"]>=8 or
                                met["lineups"][next_gw]["score"]-base_met["lineups"][next_gw]["score"]>=2)
                    if hit==4 and not (gross>=cfg["hit_rules"]["minus4_min_gross_gain"] and structural): continue
                    if hit>=8 and not (gross>=cfg["hit_rules"]["minus8_min_gross_gain"] and structural): continue
                    flex=flexibility_adjustment(squad,proj_by_id,bank,cfg["flexibility_cap_points"])
                    robust=weights["gw1"]*met["lineups"][next_gw]["robust_score"]+weights["gw3"]*sum(met["lineups"][next_gw+i]["robust_score"] for i in range(3))+weights["gw6"]*sum(met["lineups"][next_gw+i]["robust_score"] for i in range(6))
                    score=robust-hit+flex
                    p={"transfers":transfers,"squad_ids":squad,"bank_after":bank,"hit_cost":hit,"chip":None,
                       "metrics":met,"flexibility_adjustment":flex,"optimizer_score":round(score,2),
                       "lineup":met["lineups"][next_gw],"reason_flags":["structural" if structural else "points"]}
                    p["plan_id"]=_pid(p)
                    expanded.append(p)
        expanded.sort(key=lambda p:p["optimizer_score"],reverse=True)
        dedup={}
        for p in expanded:
            key=tuple(sorted(p["squad_ids"]))
            dedup.setdefault(key,p)
        frontier=list(dedup.values())[:cfg["optimizer"]["beam_width"]]
        all_plans += frontier
    all_plans.sort(key=lambda p:p["optimizer_score"],reverse=True)
    return diversify(all_plans,cfg["optimizer"]["top_plans"]), base

def plans_csv(plans, players_by_id):
    buf=io.StringIO()
    w=csv.writer(buf)
    w.writerow(["rank","plan_id","chip","transfers","hit_cost","bank_after_tenths","gw1","gw3","gw6","weighted","optimizer_score"])
    for i,p in enumerate(plans,1):
        tx="; ".join(
            f'{players_by_id[t["out"]]["web_name"]} -> {players_by_id[t["in"]]["web_name"]}' if t.get("in") is not None
            else f'{players_by_id[t["out"]]["web_name"]} -> [Free Hit rebuild]'
            for t in p["transfers"]
        ) or ("CHIP REBUILD" if p.get("chip") in {"wildcard","freehit"} else "ROLL")
        w.writerow([i,p["plan_id"],p.get("chip") or "",tx,p["hit_cost"],p["bank_after"],p["metrics"]["gw1"],p["metrics"]["gw3"],p["metrics"]["gw6"],p["metrics"]["weighted"],p["optimizer_score"]])
    return buf.getvalue()
