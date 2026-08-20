
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
from .optimizer import _ilp_squads, plan_metrics, flexibility_adjustment, diversify, _pid

def _adaptive(early,late,gw):
    start=1 if gw<=19 else 20; end=19 if gw<=19 else 38
    progress=max(0,min(1,(gw-start)/max(1,end-start)))
    return round(early+(late-early)*progress,1)

def fixture_structure(fixtures,teams,start_gw,end_gw):
    by=defaultdict(lambda:defaultdict(int))
    for f in fixtures:
        ev=f.get("event")
        if not ev or not(start_gw<=int(ev)<=end_gw): continue
        ev=int(ev); h=int(f["team_h"]); a=int(f["team_a"])
        by[ev][h]+=1; by[ev][a]+=1
    out=[]
    for gw in range(start_gw,end_gw+1):
        if not by[gw]: continue
        doubles=[teams[t] for t,c in by[gw].items() if c>=2]
        blanks=[teams[t] for t in teams if by[gw].get(t,0)==0]
        out.append({"gw":gw,"double_teams":doubles,"blank_teams":blanks,"confirmed":True,
                    "fixture_count":sum(by[gw].values())//2})
    return out

def chip_thresholds(cfg,gw):
    c=cfg["chips"]
    return {
      "freehit":_adaptive(c["free_hit_early_threshold"],c["free_hit_late_threshold"],gw),
      "wildcard":_adaptive(c["wildcard_early_threshold"],c["wildcard_late_threshold"],gw),
      "bboost":_adaptive(c["bench_boost_early_threshold"],c["bench_boost_late_threshold"],gw),
      "3xc":c["triple_captain_normal_points_target"]
    }

def opportunity_map(fixtures,teams,gw,cfg):
    end=19 if gw<=19 else 38
    structure=fixture_structure(fixtures,teams,gw,end)
    return {"thresholds":chip_thresholds(cfg,gw),"confirmed_structure":structure,
            "policy":"Confirmed blanks/doubles receive full weight. Unscheduled fixtures are never assigned to a speculative GW."}

def _current_structure(chipmap,gw):
    return next((x for x in chipmap["confirmed_structure"] if x["gw"]==gw),{"double_teams":[],"blank_teams":[]})

def augment_with_chip_plans(plans,state,players,players_by_id,proj_by_id,next_gw,cfg,chip_map):
    if not plans:return plans
    # Strategic policy: do not spend a chip in GW1. Projection/news uncertainty is maximal,
    # and future blank/double opportunities are not yet known well enough to beat opportunity cost.
    if next_gw == 1:
        return plans
    avail=state.get("chips_available",{})
    weights=cfg["projection_weights"]; bench=cfg["bench_weight"]
    out=list(plans); best=plans[0]; threshold=chip_map["thresholds"]
    structure=_current_structure(chip_map,next_gw)
    # Bench Boost: threshold is projected raw bench points, not the incremental gain.
    if avail.get("bboost") and best["lineup"]["bench_points"] >= threshold["bboost"]:
        p=deepcopy(best); p["chip"]="bboost"
        met=plan_metrics(p["squad_ids"],proj_by_id,next_gw,weights,bench,chip="bboost")
        p["metrics"]=met; p["lineup"]=met["lineups"][next_gw]
        incremental=max(0.0, (best["lineup"]["bench_points"]-threshold["bboost"])*0.8)
        p["optimizer_score"]=round(best["optimizer_score"]+incremental,2)
        p["reason_flags"]=p.get("reason_flags",[])+["Bench Boost threshold met"]
        p["plan_id"]=_pid(p); out.append(p)
    # Triple Captain: require a strong normal captain and avoid using if a stronger confirmed double appears in our 8-GW projection window.
    cap=best["lineup"]["captain"]; cap_pts=proj_by_id[cap]["per_gw"].get(next_gw,0)
    future_best=0.0
    for r in proj_by_id.values():
        if r["expected_minutes"]<65: continue
        for g,v in r["per_gw"].items():
            if int(g)>next_gw: future_best=max(future_best,float(v))
    if avail.get("3xc") and cap_pts>=threshold["3xc"] and cap_pts>=0.90*future_best:
        p=deepcopy(best); p["chip"]="3xc"
        met=plan_metrics(p["squad_ids"],proj_by_id,next_gw,weights,bench,chip="3xc")
        p["metrics"]=met; p["lineup"]=met["lineups"][next_gw]
        incremental=max(0.0, cap_pts-threshold["3xc"])
        p["optimizer_score"]=round(best["optimizer_score"]+incremental,2)
        p["reason_flags"]=p.get("reason_flags",[])+["Triple Captain threshold met"]
        p["plan_id"]=_pid(p); out.append(p)
    budget=(int(state.get("bank",0))+sum(int(x["selling_price"]) for x in state.get("squad",[]))) if state.get("squad") else 1000
    # Free Hit: legal one-week optimized squad; require material modeled one-week gain and preferably a confirmed blank/double.
    if avail.get("freehit"):
        utility=lambda pid: proj_by_id[pid]["per_gw"].get(next_gw,0)
        squads=_ilp_squads(players,proj_by_id,budget,weights,top_n=5,min_minutes_players=13,utility_override=utility)
        for squad in squads[:3]:
            met=plan_metrics(squad,proj_by_id,next_gw,weights,bench)
            gain=met["gw1"]-best["metrics"]["gw1"]
            structural=bool(structure["double_teams"] or structure["blank_teams"])
            if gain>=threshold["freehit"] and (structural or gain>=threshold["freehit"]+4):
                tx=[{"out":x["player_id"],"in":None,"sell":x["selling_price"],"buy":None} for x in state.get("squad",[])]
                p={"transfers":tx,"squad_ids":squad,"bank_after":budget-sum(proj_by_id[x]["price"] for x in squad),
                   "hit_cost":0,"chip":"freehit","metrics":met,"flexibility_adjustment":0,
                   "optimizer_score":round(met["weighted"],2),"lineup":met["lineups"][next_gw],
                   "reason_flags":[f"Free Hit modeled GW gain {gain:.1f} >= {threshold['freehit']:.1f}"]}
                p["plan_id"]=_pid(p); out.append(p)
    # Wildcard: optimize long-horizon squad and require 6-8 GW gain + structural improvement.
    if avail.get("wildcard"):
        utility=lambda pid: proj_by_id[pid]["gw8"]
        squads=_ilp_squads(players,proj_by_id,budget,weights,top_n=5,min_minutes_players=13,utility_override=utility)
        for squad in squads[:3]:
            met=plan_metrics(squad,proj_by_id,next_gw,weights,bench)
            gain=met["gw8"]-best["metrics"]["gw8"]
            forced=sum(proj_by_id[x["player_id"]]["expected_minutes"]<45 for x in state.get("squad",[]))
            if gain>=threshold["wildcard"] and (forced>=2 or gain>=threshold["wildcard"]+3):
                p={"transfers":[],"squad_ids":squad,"bank_after":budget-sum(proj_by_id[x]["price"] for x in squad),
                   "hit_cost":0,"chip":"wildcard","metrics":met,
                   "flexibility_adjustment":flexibility_adjustment(squad,proj_by_id,budget-sum(proj_by_id[x]["price"] for x in squad),cfg["flexibility_cap_points"]),
                   "optimizer_score":round(met["weighted"],2),"lineup":met["lineups"][next_gw],
                   "reason_flags":[f"Wildcard modeled 8-GW gain {gain:.1f} >= {threshold['wildcard']:.1f}"]}
                p["plan_id"]=_pid(p); out.append(p)
    out.sort(key=lambda p:p["optimizer_score"],reverse=True)
    return diversify(out,cfg["optimizer"]["top_plans"])
