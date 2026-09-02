
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
from .optimizer import _ilp_squads, plan_metrics, flexibility_adjustment, diversify, _pid
from .lineup import best_lineup
from .multigw import ManagerState, plan_multigw, structural_candidate_ids, _greedy_chip_squad, PlannerAction, transition



def wc_fh_production_enabled(cfg):
    """Wildcard/Free Hit remain shadow-only until sequential backtesting promotes them."""
    return bool(cfg.get("chips", {}).get("production_wildcard_freehit", False))


def _direct_chip_shadow_path(initial, chip, players_by_id, projections, proj_by_id, cfg, settings, horizon):
    """Construct WC/FH directly, then continue with normal no-chip planning.

    Alpha 4 asked the normal beam to *discover* a forced chip action, which could
    fail under a tight action/search budget. Alpha 5 constructs the chip squad
    first, transitions it explicitly, then searches only the remaining GWs.
    """
    mg=cfg.get("multigw",{})
    per_pos=int(settings.get("direct_chip_candidate_per_position", max(8,int(settings.get("candidate_per_position",5)))))
    candidate_ids=structural_candidate_ids(projections,initial.squad,initial.gw,horizon=max(1,horizon),per_position=per_pos)
    chip_horizon=1 if chip=="freehit" else max(1,horizon)
    squad=_greedy_chip_squad(initial,candidate_ids,players_by_id,proj_by_id,horizon=chip_horizon,bench_weight=float(cfg.get("bench_weight",.2)),discount=float(mg.get("discount",.97)))
    tr=transition(initial,PlannerAction(chip=chip,squad=tuple(squad)),players_by_id,proj_by_id,float(cfg.get("bench_weight",.2)),discount=float(mg.get("discount",.97)))
    if tr is None:
        return None
    discount=float(mg.get("discount",.97))
    first={
        "gw":initial.gw,"transfers":[],"roll":False,"chip":chip,"chip_squad":list(squad),
        "hit_cost":0,"lineup_score":round(tr.lineup_score,2),"bank_after":tr.state.bank,
        "free_transfers_after":tr.state.free_transfers,"lineup":tr.lineup,
    }
    if horizon<=1:
        return {"score":float(tr.lineup_score),"first_action":first,"steps":[first],"planner_diagnostics":{"construction":"direct_chip","continued_gws":0}}
    future=plan_multigw(
        tr.state,players_by_id,projections,proj_by_id,planning_horizon=horizon-1,
        candidate_per_position=int(settings.get("candidate_per_position",5)),beam_width=int(settings.get("beam_width",25)),
        max_transfers_per_gw=int(settings.get("max_transfers_per_gw",2)),bench_weight=float(cfg.get("bench_weight",.2)),
        discount=discount,top_n=1,cache_enabled=True,include_chips=False,dominance_pruning=True,
        runtime_budget_seconds=float(settings.get("runtime_budget_seconds_per_run",20)),
    )
    future_score=float(future[0]["score"]) if future else 0.0
    steps=[first]+(future[0].get("steps",[]) if future else [])
    return {
        "score":float(tr.lineup_score)+discount*future_score,"first_action":first,"steps":steps,
        "planner_diagnostics":{"construction":"direct_chip","continued_gws":horizon-1,"future_available":bool(future),"future":future[0].get("planner_diagnostics") if future else None},
    }


def evaluate_wc_fh_shadow(state, players_by_id, projections, proj_by_id, next_gw, cfg, chip_map, *, news_status="OK", all_low=False):
    """Compare direct WC/FH-now constructions with the best non-chip path."""
    settings = cfg.get("chips", {}).get("wc_fh_shadow", {})
    if next_gw == 1 or not settings.get("enabled", True):
        return {"status": "disabled", "production_policy": "shadow_only"}
    if state.get("mode") == "gw1_initial_build":
        return {"status": "disabled", "production_policy": "shadow_only"}

    mg = cfg.get("multigw", {})
    horizon = int(settings.get("planning_horizon", 3))
    common = dict(
        planning_horizon=horizon,candidate_per_position=int(settings.get("candidate_per_position", 5)),
        beam_width=int(settings.get("beam_width", 25)),max_transfers_per_gw=int(settings.get("max_transfers_per_gw", 2)),
        bench_weight=float(cfg.get("bench_weight", .2)),discount=float(mg.get("discount", .97)),
        top_n=1,cache_enabled=True,dominance_pruning=True,runtime_budget_seconds=float(settings.get("runtime_budget_seconds_per_run", 20)),
    )
    initial = ManagerState.from_public_state(state, next_gw)
    baseline = plan_multigw(initial, players_by_id, projections, proj_by_id, include_chips=False, **common)
    if not baseline:
        return {"status": "unavailable", "production_policy": "shadow_only", "reason": "No non-chip sequential baseline path."}
    baseline_score = float(baseline[0]["score"])
    thresholds = chip_map.get("thresholds", {})
    reserve_factor = float(settings.get("preservation_reserve_factor", .5))
    min_net = float(settings.get("minimum_net_edge_points", 4.0))
    low_mult = float(settings.get("low_confidence_edge_multiplier", 1.5))
    degraded = str(news_status).upper() == "DEGRADED"
    forced = sum(float(proj_by_id[x["player_id"]].get("expected_minutes", 90)) < 45 for x in state.get("squad", []))
    result = {"status":"available","production_policy":"shadow_only","baseline_non_chip_score":round(baseline_score,3),
              "planning_horizon":horizon,"all_low_confidence":bool(all_low),"news_status":news_status,
              "forced_low_minutes_players":forced,"chips":{},"baseline_first_action":baseline[0].get("first_action")}
    avail=state.get("chips_available",{})
    for chip,avail_key,threshold_key in (("wildcard","wildcard","wildcard"),("freehit","freehit","freehit")):
        if not avail.get(avail_key):
            result["chips"][chip]={"available":False}; continue
        path=_direct_chip_shadow_path(initial,chip,players_by_id,projections,proj_by_id,cfg,settings,horizon)
        if not path:
            result["chips"][chip]={"available":True,"evaluated":False,"reason":"Direct chip construction could not produce a legal squad."}; continue
        chip_score=float(path["score"]); gross=chip_score-baseline_score
        hurdle=float(thresholds.get(threshold_key,0.0)); min_reserve=float(settings.get(f"minimum_{chip}_preservation_points",10.0 if chip=="wildcard" else 8.0))
        preserve=max(min_reserve,reserve_factor*hurdle); net=gross-preserve; required=min_net*(low_mult if all_low else 1.0)
        confidence_gate=(not all_low) and (not degraded or forced>=2); promotion_eligible=confidence_gate and net>=required
        result["chips"][chip]={"available":True,"evaluated":True,"chip_path_score":round(chip_score,3),
            "gross_advantage_vs_best_non_chip":round(gross,3),"preservation_reserve":round(preserve,3),
            "net_opportunity_edge":round(net,3),"minimum_required_edge":round(required,3),
            "confidence_gate_passed":confidence_gate,"promotion_eligible_shadow_only":promotion_eligible,
            "first_action":path.get("first_action"),"planner_diagnostics":path.get("planner_diagnostics")}
    return result

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
    # Wildcard and Free Hit are deliberately excluded from the production plan
    # list. They are evaluated separately against the best non-chip sequential
    # path and surfaced as shadow evidence only.
    if not wc_fh_production_enabled(cfg):
        chip_map["wc_fh_policy"] = {
            "production": "shadow_only",
            "reason": "WC/FH require sequential non-chip comparison and validation before promotion."
        }
        out.sort(key=lambda p:p["optimizer_score"],reverse=True)
        return diversify(out,cfg["optimizer"]["top_plans"])
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
