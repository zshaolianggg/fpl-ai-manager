
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
from .optimizer import _ilp_squads, plan_metrics, flexibility_adjustment, diversify, _pid
from .lineup import best_lineup

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



def _projection_gws(proj_by_id, start_gw, half_end):
    gws=set()
    for row in proj_by_id.values():
        for g in row.get("per_gw", {}):
            g=int(g)
            if start_gw <= g <= half_end:
                gws.add(g)
    return sorted(gws)


def bench_boost_increment(squad_ids, proj_by_id, gw, bench_weight=0.2):
    normal=best_lineup(squad_ids,proj_by_id,gw,bench_weight,selection_mode="probabilistic")
    boosted=best_lineup(squad_ids,proj_by_id,gw,bench_weight,bench_boost=True,selection_mode="probabilistic")
    return max(0.0,float(boosted["probabilistic_score"])-float(normal["probabilistic_score"]))


def triple_captain_increment(squad_ids, proj_by_id, gw, bench_weight=0.2):
    normal=best_lineup(squad_ids,proj_by_id,gw,bench_weight,selection_mode="probabilistic")
    model=normal.get("captaincy_model") or {}
    # One additional captain copy beyond ordinary captaincy. The captaincy model
    # already includes vice takeover when the captain records zero minutes.
    return max(0.0,float(model.get("expected_extra_points") or proj_by_id[normal["captain"]]["per_gw"].get(gw,0)))


def chip_opportunity_costs(squad_ids, proj_by_id, next_gw, cfg):
    half_end=19 if next_gw<=19 else 38
    gws=_projection_gws(proj_by_id,next_gw,half_end)
    bench_weight=float(cfg.get("bench_weight",0.2))
    bb={g:bench_boost_increment(squad_ids,proj_by_id,g,bench_weight) for g in gws}
    tc={g:triple_captain_increment(squad_ids,proj_by_id,g,bench_weight) for g in gws}
    future_bb=max((v for g,v in bb.items() if g>next_gw),default=0.0)
    future_tc=max((v for g,v in tc.items() if g>next_gw),default=0.0)
    c=cfg.get("chips",{})
    reserve=float(c.get("future_opportunity_reserve_factor",0.90))
    min_edge=float(c.get("minimum_opportunity_edge_points",1.0))
    return {
        "bench_boost": {"current":round(bb.get(next_gw,0.0),3),"future_best":round(future_bb,3),"opportunity_cost":round(reserve*future_bb,3),"net":round(bb.get(next_gw,0.0)-reserve*future_bb,3),"minimum_edge":min_edge},
        "triple_captain": {"current":round(tc.get(next_gw,0.0),3),"future_best":round(future_tc,3),"opportunity_cost":round(reserve*future_tc,3),"net":round(tc.get(next_gw,0.0)-reserve*future_tc,3),"minimum_edge":min_edge},
        "evaluated_gws": gws,
        "reserve_factor": reserve,
    }


def _future_structure_reserve(chip_map, next_gw, cfg):
    c=cfg.get("chips",{})
    per_gw=float(c.get("confirmed_structure_reserve_points",2.0))
    future=[x for x in chip_map.get("confirmed_structure",[]) if int(x["gw"])>int(next_gw) and (x.get("double_teams") or x.get("blank_teams"))]
    return min(float(c.get("max_structure_reserve_points",6.0)), per_gw*len(future))

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
    opportunity=chip_opportunity_costs(best["squad_ids"],proj_by_id,next_gw,cfg)
    chip_map["modeled_opportunity_costs"]=opportunity
    # Bench Boost: compare its incremental value now with the best modeled
    # future opportunity in the available projection window.
    bb_opp=opportunity["bench_boost"]
    if avail.get("bboost") and bb_opp["net"] >= bb_opp["minimum_edge"]:
        p=deepcopy(best); p["chip"]="bboost"
        met=plan_metrics(p["squad_ids"],proj_by_id,next_gw,weights,bench,chip="bboost")
        p["metrics"]=met; p["lineup"]=met["lineups"][next_gw]
        p["optimizer_score"]=round(best["optimizer_score"]+bb_opp["net"],2)
        p["reason_flags"]=p.get("reason_flags",[])+[f"Bench Boost net opportunity edge {bb_opp['net']:.1f} (now {bb_opp['current']:.1f} vs reserved future {bb_opp['opportunity_cost']:.1f})"]
        p["plan_id"]=_pid(p); out.append(p)
    # Triple Captain: same opportunity-cost principle, using the probabilistic
    # captain/vice pair value rather than a fixed captain-points target.
    tc_opp=opportunity["triple_captain"]
    if avail.get("3xc") and tc_opp["net"] >= tc_opp["minimum_edge"]:
        p=deepcopy(best); p["chip"]="3xc"
        met=plan_metrics(p["squad_ids"],proj_by_id,next_gw,weights,bench,chip="3xc")
        p["metrics"]=met; p["lineup"]=met["lineups"][next_gw]
        p["optimizer_score"]=round(best["optimizer_score"]+tc_opp["net"],2)
        p["reason_flags"]=p.get("reason_flags",[])+[f"Triple Captain net opportunity edge {tc_opp['net']:.1f} (now {tc_opp['current']:.1f} vs reserved future {tc_opp['opportunity_cost']:.1f})"]
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
            fh_required=threshold["freehit"]+_future_structure_reserve(chip_map,next_gw,cfg)
            if gain>=fh_required and (structural or gain>=fh_required+4):
                tx=[{"out":x["player_id"],"in":None,"sell":x["selling_price"],"buy":None} for x in state.get("squad",[])]
                p={"transfers":tx,"squad_ids":squad,"bank_after":budget-sum(proj_by_id[x]["price"] for x in squad),
                   "hit_cost":0,"chip":"freehit","metrics":met,"flexibility_adjustment":0,
                   "optimizer_score":round(met["weighted"],2),"lineup":met["lineups"][next_gw],
                   "reason_flags":[f"Free Hit modeled GW gain {gain:.1f} >= opportunity-adjusted hurdle {fh_required:.1f}"]}
                p["plan_id"]=_pid(p); out.append(p)
    # Wildcard: optimize long-horizon squad and require 6-8 GW gain + structural improvement.
    if avail.get("wildcard"):
        utility=lambda pid: proj_by_id[pid]["gw8"]
        squads=_ilp_squads(players,proj_by_id,budget,weights,top_n=5,min_minutes_players=13,utility_override=utility)
        for squad in squads[:3]:
            met=plan_metrics(squad,proj_by_id,next_gw,weights,bench)
            gain=met["gw8"]-best["metrics"]["gw8"]
            forced=sum(proj_by_id[x["player_id"]]["expected_minutes"]<45 for x in state.get("squad",[]))
            wc_required=threshold["wildcard"]+0.5*_future_structure_reserve(chip_map,next_gw,cfg)
            if gain>=wc_required and (forced>=2 or gain>=wc_required+3):
                p={"transfers":[],"squad_ids":squad,"bank_after":budget-sum(proj_by_id[x]["price"] for x in squad),
                   "hit_cost":0,"chip":"wildcard","metrics":met,
                   "flexibility_adjustment":flexibility_adjustment(squad,proj_by_id,budget-sum(proj_by_id[x]["price"] for x in squad),cfg["flexibility_cap_points"]),
                   "optimizer_score":round(met["weighted"],2),"lineup":met["lineups"][next_gw],
                   "reason_flags":[f"Wildcard modeled 8-GW gain {gain:.1f} >= opportunity-adjusted hurdle {wc_required:.1f}"]}
                p["plan_id"]=_pid(p); out.append(p)
    out.sort(key=lambda p:p["optimizer_score"],reverse=True)
    return diversify(out,cfg["optimizer"]["top_plans"])
