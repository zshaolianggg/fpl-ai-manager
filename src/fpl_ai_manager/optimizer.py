
from __future__ import annotations
from dataclasses import dataclass
from itertools import combinations
from collections import Counter
import csv, io, hashlib, json
try:
    import pulp
except ModuleNotFoundError:  # Allows non-ILP utilities/tests in lightweight environments.
    pulp = None
from .lineup import best_lineup, robust_points
from .validator import validate_squad, validate_plan

def _pid(plan): 
    raw=json.dumps({"t":plan.get("transfers",[]),"c":plan.get("chip"),"s":sorted(plan.get("squad_ids",[]))},sort_keys=True)
    return hashlib.sha1(raw.encode()).hexdigest()[:10]

def plan_metrics(squad_ids, proj_by_id, next_gw, weights, bench_weight, chip=None, selection_mode="robust"):

    per={}
    lineups={}
    for i in range(8):
        gw=next_gw+i
        lu=best_lineup(squad_ids,proj_by_id,gw,bench_weight,
                       bench_boost=(chip=="bboost" and i==0),
                       triple_captain=(chip=="3xc" and i==0),
                       selection_mode=selection_mode)
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
    if pulp is None:
        raise RuntimeError("PuLP is required for ILP squad optimization. Install project dependencies first.")
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
    if pulp is None:
        raise RuntimeError("PuLP is required for GW1 ILP squad optimization. Install project dependencies first.")
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

def _gw1_structural_diagnostics(squad, met, proj_by_id, next_gw):
    """Explain whether GW1 budget is being parked in players unlikely to be used.

    This is diagnostic/secondary utility only. It deliberately does not impose a
    hard price ceiling on the bench: an expensive benched player is allowed when
    the multi-GW projection demonstrates enough future/auto-sub value.
    """
    lu = met["lineups"][next_gw]
    bench = list(lu.get("bench", []))
    dormant = 0.0
    expensive = []
    outfield_slot = 0
    for pid in bench:
        row = proj_by_id[pid]
        if row.get("position") == 1:
            continue
        outfield_slot += 1
        price = float(row.get("price") or 0)
        p_app = float((row.get("minutes_projection") or {}).get("p_appearance") or min(1.0, float(row.get("expected_minutes") or 0)/65.0))
        # Probability of actually being called from this bench slot is approximated
        # by the lineup engine's total auto-sub value allocation: later slots are
        # increasingly dormant. This is a capital-efficiency signal, not points.
        slot_use = {1: .18, 2: .09, 3: .04}.get(outfield_slot, .03) * p_app
        dormant += price * (1.0-slot_use)
        if price >= 70 and outfield_slot >= 2:
            expensive.append(pid)
    starting_cost = sum(float(proj_by_id[p]["price"]) for p in lu.get("starters", []))
    bench_cost = sum(float(proj_by_id[p]["price"]) for p in bench)
    future_starts={pid:0 for pid in expensive}
    for offset in range(1,6):
        future_lu=met.get("lineups",{}).get(next_gw+offset) or {}
        for pid in expensive:
            if pid in future_lu.get("starters",[]):
                future_starts[pid] += 1
    return {
        "starting_cost_tenths": round(starting_cost, 1),
        "bench_cost_tenths": round(bench_cost, 1),
        "dormant_capital_index": round(dormant/10.0, 2),
        "expensive_deep_bench": expensive,
        "expensive_deep_bench_future_starts_next5": future_starts,
        "expected_auto_sub_points": float(lu.get("expected_auto_sub_points") or 0),
        "probabilistic_lineup_score": float(lu.get("probabilistic_score") or lu.get("score") or 0),
    }


def _gw1_v3_score(squad, met, proj_by_id, next_gw, weights, bank, cfg):
    """V3 GW1 reranker: probabilistic usable points first, structure second."""
    # The horizons overlap by design to preserve V2 semantics, but use the
    # probabilistic lineup score (auto-subs + captain fallback) rather than a
    # fixed percentage of all bench points.
    prob1 = met["lineups"][next_gw]["probabilistic_score"]
    prob3 = sum(met["lineups"][next_gw+i]["probabilistic_score"] for i in range(3))
    prob6 = sum(met["lineups"][next_gw+i]["probabilistic_score"] for i in range(6))
    core = weights["gw1"]*prob1 + weights["gw3"]*prob3 + weights["gw6"]*prob6
    diag = _gw1_structural_diagnostics(squad, met, proj_by_id, next_gw)

    gw1_cfg = cfg.get("gw1", {})
    future_starts=diag.get("expensive_deep_bench_future_starts_next5",{})
    deep_bench_penalty = 0.0
    for pid in diag["expensive_deep_bench"]:
        # If the expensive asset becomes a regular starter immediately, the
        # apparent GW1 dormancy is justified by explicit multi-GW utility.
        starts=float(future_starts.get(pid,0))
        persistence=max(0.0, 1.0-min(1.0, starts/3.0))
        deep_bench_penalty += float(gw1_cfg.get("expensive_deep_bench_penalty", .45))*persistence
    # Dormant-capital penalty is intentionally tiny and capped: it only breaks
    # near-ties unless the squad parks several millions in deep bench slots.
    dormant_free = float(gw1_cfg.get("dormant_capital_free_index", 17.0))
    dormant_penalty = min(float(gw1_cfg.get("dormant_capital_penalty_cap", 1.5)),
                          max(0.0, diag["dormant_capital_index"]-dormant_free) * float(gw1_cfg.get("dormant_capital_penalty_per_index", .08)))
    excess_bank_penalty=max(0,(bank-float(gw1_cfg.get("max_unpenalized_bank_tenths",10)))/5)*.35
    flex=max(0, flexibility_adjustment(squad,proj_by_id,bank,cfg["flexibility_cap_points"])-excess_bank_penalty)
    return round(core + flex - deep_bench_penalty - dormant_penalty, 3), diag, round(flex,2)


def initial_build_plans(players, players_by_id, proj_by_id, next_gw, cfg):
    """V3-aware GW1 build.

    ILP is now only the broad legal candidate generator. Final ranking is based
    on probabilistic lineup utility and structural capital efficiency, removing
    the old assumption that every bench player's points are worth a fixed 20%.
    """
    weights=cfg["projection_weights"]
    # Keep the old bench coefficient only to generate a broad candidate set;
    # it is *not* the final ranking objective.
    generator_bench=float(cfg.get("gw1",{}).get("candidate_generator_bench_weight", .08))
    candidate_count=max(int(cfg.get("gw1",{}).get("candidate_squads",80)), cfg["optimizer"]["top_plans"]*3)
    squads=_gw1_ilp_squads(players,proj_by_id,1000,weights,generator_bench,candidate_count)
    plans=[]
    for candidate_rank, squad in enumerate(squads,1):
        spend=sum(proj_by_id[p]["price"] for p in squad)
        bank=1000-spend
        met=plan_metrics(squad,proj_by_id,next_gw,weights,0.0,selection_mode="probabilistic")
        v3_score, diag, flex = _gw1_v3_score(squad,met,proj_by_id,next_gw,weights,bank,cfg)
        plan={"transfers":[],"squad_ids":squad,"bank_after":bank,"hit_cost":0,"chip":None,
              "metrics":met,"flexibility_adjustment":flex,
              "optimizer_score":v3_score,"lineup":met["lineups"][next_gw],
              "optimizer_engine":"V3_GW1_PROBABILISTIC_RERANK",
              "candidate_generator_rank":candidate_rank,
              "structural_diagnostics":diag,
              "reason_flags":["GW1 probabilistic lineup optimization","auto-sub-aware bench valuation","structural capital diagnostics"]}
        plan["plan_id"]=_pid(plan)
        if not validate_plan(plan,players_by_id,proj_by_id):
            plans.append(plan)
    plans.sort(key=lambda p:p["optimizer_score"],reverse=True)
    plans=cluster_sort(plans,proj_by_id,float(cfg["optimizer"].get("near_tie_cluster_width_points",.50)))
    return diversify(plans,cfg["optimizer"]["top_plans"])

def robustness_tiebreak(plan, proj_by_id):
    squad=plan["squad_ids"]
    low_minutes=sum(proj_by_id[p].get("expected_minutes",0)<65 for p in squad)
    low_conf=sum(proj_by_id[p].get("confidence")=="LOW" for p in squad)
    expensive_bench=sum(1 for p in plan["lineup"].get("bench",[])
                        if proj_by_id[p]["position"] in {3,4} and proj_by_id[p].get("price",0)>=70)
    captain=plan["lineup"]["captain"]
    cap_row=proj_by_id[captain]
    cap_quality=(1 if cap_row["position"] in {3,4} else 0)+(1 if cap_row.get("expected_minutes",0)>=75 else 0)
    return round(0.35*cap_quality - 0.08*low_minutes - 0.03*low_conf - 0.25*expensive_bench,3)

def cluster_sort(plans, proj_by_id, cluster_width=.50):
    if not plans:return plans
    plans=sorted(plans,key=lambda p:p["optimizer_score"],reverse=True)
    top=plans[0]["optimizer_score"]
    cluster=[p for p in plans if top-p["optimizer_score"]<=cluster_width]
    rest=[p for p in plans if top-p["optimizer_score"]>cluster_width]
    for p in cluster:
        p["robustness_tiebreak"]=robustness_tiebreak(p,proj_by_id)
    cluster.sort(key=lambda p:(p["robustness_tiebreak"],p["optimizer_score"]),reverse=True)
    return cluster+rest

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
    all_plans=cluster_sort(all_plans,proj_by_id,0.50)
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
