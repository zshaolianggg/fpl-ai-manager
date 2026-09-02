from __future__ import annotations


def _transfer_pairs_from_v2(plan):
    return tuple(sorted((int(t["out"]), int(t["in"])) for t in (plan.get("transfers") or []) if t.get("in") is not None))


def _transfer_pairs_from_v3(path):
    first=(path or {}).get("first_action") or {}
    return tuple(sorted((int(t["out"]), int(t.get("in") if t.get("in") is not None else t.get("in_"))) for t in first.get("transfers", []) if t.get("in") is not None or t.get("in_") is not None))


def compare_v2_v3(v2_plan, v3_paths):
    """Compact, auditable comparison of production V2 and shadow V3 first actions.

    Native V2 optimizer scores and V3 path scores are intentionally labelled as
    non-comparable: they use different objectives/horizons. A separate
    common_basis block may be attached later by evaluate_common_basis().
    """
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
        "status":"available",
        "label":label,
        "same_first_action":same,
        "v2_plan_id":v2_plan.get("plan_id"),
        "v2_optimizer_score":v2_plan.get("optimizer_score"),
        "v2_transfers":[{"out":a,"in":b} for a,b in v2_tx],
        "v2_roll":v2_roll,"v2_chip":v2_chip,
        "v3_path_score":v3.get("score"),
        "native_scores_comparable":False,
        "native_score_note":"V2 optimizer_score and V3 path score use different objectives/horizons and must not be compared directly.",
        "v3_transfers":[{"out":a,"in":b} for a,b in v3_tx],
        "v3_roll":v3_roll,"v3_chip":v3_chip,
        "v3_future_steps":future_steps,
        "v3_first_action":first,
        "v3_planner_diagnostics":v3.get("planner_diagnostics"),
    }


def evaluate_common_basis(v2_plan, v3_path, initial_state, players_by_id, projections, proj_by_id, *,
                          horizon=3, candidate_per_position=5, beam_width=20,
                          max_transfers_per_gw=2, bench_weight=.2, discount=.97,
                          runtime_budget_seconds=8):
    """Evaluate V2 and V3 routes on the same probabilistic sequential objective.

    V2's selected first action is forced, then the same V3 planner is allowed to
    choose the best continuation. V3 is read from its already-computed path.
    This produces apples-to-apples route scores without conflating native V2
    optimizer_score with V3 path score.
    """
    from .multigw import Transfer, transition, plan_multigw

    if not v2_plan or not v3_path or not initial_state:
        return {"status":"unavailable"}
    if v2_plan.get("chip"):
        return {"status":"unavailable","reason":"production chip route not supported in common-basis comparison"}

    transfers=tuple(Transfer(int(t["out"]),int(t["in"])) for t in (v2_plan.get("transfers") or []))
    tr=transition(initial_state, transfers, players_by_id, proj_by_id, bench_weight=bench_weight, discount=discount)
    if tr is None:
        return {"status":"unavailable","reason":"V2 first action could not be replayed in V3 state model"}
    v2_first=float(tr.lineup_score)-float(tr.hit_cost)
    v2_total=v2_first
    v2_steps=[{"gw":initial_state.gw,"lineup_score":round(tr.lineup_score,2),"hit_cost":tr.hit_cost,"bank_after":tr.state.bank,"free_transfers_after":tr.state.free_transfers}]
    if horizon > 1:
        cont=plan_multigw(
            tr.state,players_by_id,projections,proj_by_id,
            planning_horizon=horizon-1,candidate_per_position=candidate_per_position,
            beam_width=beam_width,max_transfers_per_gw=max_transfers_per_gw,
            bench_weight=bench_weight,discount=discount,top_n=1,
            cache_enabled=True,include_chips=False,dominance_pruning=True,
            runtime_budget_seconds=runtime_budget_seconds,
        )
        if cont:
            v2_total += discount*float(cont[0]["score"])
            v2_steps.extend(cont[0].get("steps") or [])

    v3_steps=(v3_path.get("steps") or [])[:horizon]
    v3_total=0.0
    for depth,step in enumerate(v3_steps):
        v3_total += (discount**depth)*(float(step.get("lineup_score") or 0)-float(step.get("hit_cost") or 0))

    return {
        "status":"available",
        "horizon_gws":horizon,
        "objective":"probabilistic sequential lineup points net of hits; same discount for both routes",
        "v2_score":round(v2_total,3),
        "v3_score":round(v3_total,3),
        "delta_v3_minus_v2":round(v3_total-v2_total,3),
        "v2_first_gw_score":round(v2_first,3),
        "v3_first_gw_score":round((float(v3_steps[0].get("lineup_score") or 0)-float(v3_steps[0].get("hit_cost") or 0)) if v3_steps else 0,3),
        "v2_bank_after_first":tr.state.bank,
        "v3_bank_after_first":v3_steps[0].get("bank_after") if v3_steps else None,
        "v2_steps":v2_steps[:horizon],
        "v3_steps":v3_steps,
    }
