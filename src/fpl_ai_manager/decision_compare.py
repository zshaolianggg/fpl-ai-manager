from __future__ import annotations


def _transfer_pairs_from_v2(plan):
    return tuple(sorted((int(t["out"]), int(t["in"])) for t in (plan.get("transfers") or []) if t.get("in") is not None))


def _transfer_pairs_from_v3(path):
    first=(path or {}).get("first_action") or {}
    return tuple(sorted((int(t["out"]), int(t.get("in") if t.get("in") is not None else t.get("in_"))) for t in first.get("transfers", []) if t.get("in") is not None or t.get("in_") is not None))


def compare_v2_v3(v2_plan, v3_paths):
    if not v2_plan:
        return {"status":"unavailable","reason":"missing V2 plan"}
    if not v3_paths:
        return {"status":"unavailable","reason":"V3 shadow unavailable"}
    v3=v3_paths[0]
    v2_tx=_transfer_pairs_from_v2(v2_plan)
    v3_tx=_transfer_pairs_from_v3(v3)
    v2_roll=not v2_tx
    first=v3.get("first_action") or {}
    v3_roll=bool(first.get("roll")) or (not v3_tx and not first.get("chip"))
    v2_chip=v2_plan.get("chip")
    v3_chip=first.get("chip")
    same_action=(v2_roll and v3_roll) or (v2_tx==v3_tx and bool(v2_tx))
    same=bool(same_action and v2_chip==v3_chip)
    if same:
        label="AGREE"
    elif v2_roll != v3_roll:
        label="MATERIAL_DISAGREEMENT"
    else:
        label="DIFFERENT_ROUTE"
    future_steps=[]
    for step in (v3.get("steps") or [])[:3]:
        tx=[]
        for t in step.get("transfers",[]) or []:
            incoming=t.get("in") if t.get("in") is not None else t.get("in_")
            if incoming is not None:
                tx.append({"out":int(t["out"]),"in":int(incoming)})
        future_steps.append({
            "gw":step.get("gw"),"transfers":tx,"roll":bool(step.get("roll")),"chip":step.get("chip"),
            "hit_cost":step.get("hit_cost"),"bank_after":step.get("bank_after"),"free_transfers_after":step.get("free_transfers_after"),
            "lineup_score":step.get("lineup_score"),
        })
    return {
        "status":"available","label":label,"same_first_action":same,
        "v2_plan_id":v2_plan.get("plan_id"),"v2_optimizer_score":v2_plan.get("optimizer_score"),
        "v2_transfers":[{"out":a,"in":b} for a,b in v2_tx],"v2_roll":v2_roll,"v2_chip":v2_chip,
        "v3_path_score":v3.get("score"),"native_scores_comparable":False,
        "native_score_note":"V2 optimizer_score and V3 path score use different objectives/horizons and must not be compared directly.",
        "v3_transfers":[{"out":a,"in":b} for a,b in v3_tx],"v3_roll":v3_roll,"v3_chip":v3_chip,
        "v3_future_steps":future_steps,"v3_first_action":first,"v3_planner_diagnostics":v3.get("planner_diagnostics"),
    }


def _forced_first_route(initial_state, transfers, players_by_id, projections, proj_by_id, *,
                        horizon, candidate_per_position, beam_width, max_transfers_per_gw,
                        bench_weight, discount, runtime_budget_seconds):
    from .multigw import transition, plan_multigw

    tr=transition(initial_state, transfers, players_by_id, proj_by_id, bench_weight=bench_weight, discount=discount)
    if tr is None:
        return {"status":"unavailable","reason":"first action could not be replayed in V3 state model"}

    first_value=float(tr.lineup_score)-float(tr.hit_cost)
    steps=[{"gw":int(initial_state.gw),"lineup_score":round(float(tr.lineup_score),3),"hit_cost":int(tr.hit_cost),
            "net_score":round(first_value,3),"bank_after":int(tr.state.bank),"free_transfers_after":int(tr.state.free_transfers)}]
    total=first_value
    remaining=max(0,int(horizon)-1)
    if remaining:
        cont=plan_multigw(
            tr.state,players_by_id,projections,proj_by_id,
            planning_horizon=remaining,candidate_per_position=candidate_per_position,beam_width=beam_width,
            max_transfers_per_gw=max_transfers_per_gw,bench_weight=bench_weight,discount=discount,top_n=1,
            cache_enabled=True,include_chips=False,dominance_pruning=True,runtime_budget_seconds=runtime_budget_seconds,
        )
        if not cont:
            return {"status":"unavailable","reason":"continuation search returned no path"}
        csteps=cont[0].get("steps") or []
        if len(csteps) != remaining:
            diag=cont[0].get("planner_diagnostics") or {}
            return {"status":"unavailable","reason":f"continuation horizon incomplete: expected {remaining} future GW(s), got {len(csteps)}","timed_out":bool(diag.get("timed_out"))}
        total += float(discount)*float(cont[0]["score"])
        for s in csteps:
            net=float(s.get("lineup_score") or 0)-float(s.get("hit_cost") or 0)
            steps.append({"gw":int(s.get("gw")),"lineup_score":round(float(s.get("lineup_score") or 0),3),
                          "hit_cost":int(s.get("hit_cost") or 0),"net_score":round(net,3),"bank_after":s.get("bank_after"),
                          "free_transfers_after":s.get("free_transfers_after")})

    expected_gws=list(range(int(initial_state.gw),int(initial_state.gw)+int(horizon)))
    actual_gws=[int(s["gw"]) for s in steps]
    if len(steps) != int(horizon) or actual_gws != expected_gws:
        return {"status":"unavailable","reason":f"route horizon mismatch: expected {expected_gws}, got {actual_gws}"}
    return {"status":"available","score":float(total),"steps":steps,"bank_after_first":tr.state.bank}


def evaluate_common_basis(v2_plan, v3_path, initial_state, players_by_id, projections, proj_by_id, *,
                          horizon=3, candidate_per_position=5, beam_width=20,
                          max_transfers_per_gw=2, bench_weight=.2, discount=.97,
                          runtime_budget_seconds=8):
    """Compare V2/V3 first actions on exactly the same gameweeks and objective."""
    from .multigw import Transfer

    if not v2_plan or not v3_path or not initial_state:
        return {"status":"unavailable","reason":"missing route inputs"}
    if v2_plan.get("chip"):
        return {"status":"unavailable","reason":"production chip route not supported in common-basis comparison"}

    v2_transfers=tuple(Transfer(int(t["out"]),int(t["in"])) for t in (v2_plan.get("transfers") or []))
    first=(v3_path.get("first_action") or {})
    if first.get("chip"):
        return {"status":"unavailable","reason":"V3 chip route not supported in common-basis comparison"}
    v3_transfers=tuple(Transfer(int(t["out"]),int(t.get("in") if t.get("in") is not None else t.get("in_")))
                       for t in (first.get("transfers") or []) if t.get("in") is not None or t.get("in_") is not None)

    kwargs=dict(horizon=int(horizon),candidate_per_position=int(candidate_per_position),beam_width=int(beam_width),
                max_transfers_per_gw=int(max_transfers_per_gw),bench_weight=float(bench_weight),discount=float(discount),
                runtime_budget_seconds=float(runtime_budget_seconds))
    v2=_forced_first_route(initial_state,v2_transfers,players_by_id,projections,proj_by_id,**kwargs)
    v3=_forced_first_route(initial_state,v3_transfers,players_by_id,projections,proj_by_id,**kwargs)
    if v2.get("status") != "available" or v3.get("status") != "available":
        reasons=[]
        if v2.get("status") != "available": reasons.append(f"V2: {v2.get('reason','unavailable')}")
        if v3.get("status") != "available": reasons.append(f"V3: {v3.get('reason','unavailable')}")
        return {"status":"unavailable","reason":"; ".join(reasons),"requested_horizon_gws":int(horizon)}

    v2_gws=[s["gw"] for s in v2["steps"]]; v3_gws=[s["gw"] for s in v3["steps"]]
    if v2_gws != v3_gws:
        return {"status":"unavailable","reason":f"common-basis GW mismatch: V2 {v2_gws}, V3 {v3_gws}"}
    return {
        "status":"available","horizon_gws":int(horizon),"evaluated_gws":v2_gws,
        "objective":"probabilistic sequential lineup points net of hits; identical GWs, discount and continuation planner",
        "v2_score":round(float(v2["score"]),3),"v3_score":round(float(v3["score"]),3),
        "delta_v3_minus_v2":round(float(v3["score"])-float(v2["score"]),3),
        "v2_first_gw_score":round(float(v2["steps"][0]["net_score"]),3),"v3_first_gw_score":round(float(v3["steps"][0]["net_score"]),3),
        "v2_bank_after_first":v2["bank_after_first"],"v3_bank_after_first":v3["bank_after_first"],
        "v2_steps":v2["steps"],"v3_steps":v3["steps"],
    }
