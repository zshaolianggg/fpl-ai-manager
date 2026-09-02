from __future__ import annotations
from copy import deepcopy
from ..optimizer import managed_plans
from ..multigw import ManagerState, plan_multigw
from ..decision_compare import compare_v2_v3
from .snapshots import validate_no_future_leakage


def replay_snapshot(snapshot: dict):
    """Replay V2 and V3 from a frozen pre-deadline snapshot.

    The snapshot must already contain projections generated with only information
    available by its deadline. This function performs no network access.
    """
    validate_no_future_leakage(snapshot)
    state=deepcopy(snapshot["state"])
    players_by_id={int(k):v for k,v in snapshot["players_by_id"].items()} if isinstance(snapshot["players_by_id"],dict) else {int(p["id"]):p for p in snapshot["players_by_id"]}
    projections=deepcopy(snapshot["projections"])
    proj_by_id={int(r["player_id"]):r for r in projections}
    cfg=deepcopy(snapshot["config"])
    gw=int(snapshot["gameweek"])
    v2,_=managed_plans(state,players_by_id,projections,proj_by_id,gw,cfg)
    mg=cfg.get("multigw",{})
    v3=plan_multigw(
        ManagerState.from_public_state(state,gw),players_by_id,projections,proj_by_id,
        planning_horizon=int(mg.get("planning_horizon",4)),
        candidate_per_position=int(mg.get("candidate_per_position",8)),
        beam_width=int(mg.get("beam_width",60)),
        max_transfers_per_gw=int(mg.get("max_transfers_per_gw",2)),
        bench_weight=float(cfg.get("bench_weight",.2)),discount=float(mg.get("discount",.97)),
        top_n=12,cache_enabled=bool(mg.get("cache_enabled",True)),include_chips=False,
        dominance_pruning=bool(mg.get("dominance_pruning",True)),
        runtime_budget_seconds=float(mg.get("runtime_budget_seconds",45)),
    )
    return {"v2":v2,"v3":v3,"comparison":compare_v2_v3(v2[0] if v2 else None,v3)}
