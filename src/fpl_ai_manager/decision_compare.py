from __future__ import annotations


def _transfer_pairs_from_v2(plan):
    return tuple(sorted((int(t["out"]), int(t["in"])) for t in (plan.get("transfers") or []) if t.get("in") is not None))


def _transfer_pairs_from_v3(path):
    first=(path or {}).get("first_action") or {}
    return tuple(sorted((int(t["out"]), int(t.get("in") if t.get("in") is not None else t.get("in_"))) for t in first.get("transfers", []) if t.get("in") is not None or t.get("in_") is not None))


def compare_v2_v3(v2_plan, v3_paths):
    """Compact, auditable comparison of production V2 and shadow V3 first actions."""
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
        "v3_transfers":[{"out":a,"in":b} for a,b in v3_tx],
        "v3_roll":v3_roll,"v3_chip":v3_chip,
        "v3_future_steps":future_steps,
        "v3_first_action":first,
        "v3_planner_diagnostics":v3.get("planner_diagnostics"),
    }
