from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Iterable

from .lineup import best_lineup
from .validator import validate_squad


@dataclass(frozen=True)
class Transfer:
    out: int
    in_: int

    def as_dict(self):
        return {"out": self.out, "in": self.in_}


@dataclass(frozen=True)
class ManagerState:
    """Decision state at the start of a gameweek.

    Prices are held in FPL tenths. Newly bought players enter the ledger at
    current price; future live price-change modelling is intentionally deferred
    to the V3.3 price layer.
    """

    gw: int
    squad: tuple[int, ...]
    bank: int
    free_transfers: int
    sell_prices: tuple[tuple[int, int], ...]

    @classmethod
    def from_public_state(cls, state: dict, gw: int):
        squad = tuple(sorted(int(x["player_id"]) for x in state["squad"]))
        sell = tuple(sorted((int(x["player_id"]), int(x["selling_price"])) for x in state["squad"]))
        return cls(gw=int(gw), squad=squad, bank=int(state["bank"]), free_transfers=int(state["free_transfers"]), sell_prices=sell)

    @property
    def sell_price_map(self):
        return dict(self.sell_prices)

    def key(self):
        return self.gw, self.squad, self.bank, self.free_transfers, self.sell_prices


@dataclass(frozen=True)
class Transition:
    state: ManagerState
    transfers: tuple[Transfer, ...]
    hit_cost: int
    lineup_score: float
    lineup: dict


@dataclass
class Path:
    state: ManagerState
    score: float
    steps: list[dict]


@dataclass
class PlannerCache:
    """Per-run memoization for the beam search.

    The same squad/state appears repeatedly through different transfer paths.
    Caching lineup evaluation and legal actions avoids recomputing the most
    expensive deterministic work without leaking state between deadline runs.
    """
    lineups: dict = field(default_factory=dict)
    actions: dict = field(default_factory=dict)
    transitions: dict = field(default_factory=dict)
    lineup_hits: int = 0
    lineup_misses: int = 0
    action_hits: int = 0
    action_misses: int = 0
    transition_hits: int = 0
    transition_misses: int = 0

    def diagnostics(self):
        return {
            "lineup_cache_hits": self.lineup_hits, "lineup_cache_misses": self.lineup_misses,
            "action_cache_hits": self.action_hits, "action_cache_misses": self.action_misses,
            "transition_cache_hits": self.transition_hits, "transition_cache_misses": self.transition_misses,
            "unique_lineups": len(self.lineups), "unique_action_states": len(self.actions),
            "unique_transitions": len(self.transitions),
        }


def _next_free_transfers(start_ft: int, transfers: int) -> int:
    remaining = max(0, int(start_ft)-int(transfers))
    return min(5, remaining+1)


def apply_transfers(
    state: ManagerState,
    transfers: Iterable[Transfer],
    players_by_id: dict,
    proj_by_id: dict,
) -> tuple[ManagerState, int] | None:
    transfers = tuple(transfers)
    outs = [t.out for t in transfers]
    ins = [t.in_ for t in transfers]
    if len(set(outs)) != len(outs) or len(set(ins)) != len(ins):
        return None
    owned = set(state.squad)
    if not set(outs).issubset(owned) or set(ins) & (owned-set(outs)):
        return None

    sell = state.sell_price_map
    bank = int(state.bank)
    squad = list(state.squad)
    new_sell = dict(sell)
    for t in transfers:
        if t.out not in proj_by_id or t.in_ not in proj_by_id:
            return None
        if int(proj_by_id[t.out]["position"]) != int(proj_by_id[t.in_]["position"]):
            return None
        bank += int(sell[t.out]) - int(proj_by_id[t.in_]["price"])
        if bank < 0:
            return None
        squad.remove(t.out)
        squad.append(t.in_)
        new_sell.pop(t.out, None)
        new_sell[t.in_] = int(proj_by_id[t.in_]["price"])

    squad = tuple(sorted(squad))
    if validate_squad(list(squad), players_by_id):
        return None
    hit = max(0, len(transfers)-int(state.free_transfers))*4
    nxt = ManagerState(
        gw=state.gw+1,
        squad=squad,
        bank=bank,
        free_transfers=_next_free_transfers(state.free_transfers, len(transfers)),
        sell_prices=tuple(sorted(new_sell.items())),
    )
    return nxt, hit


def _future_points(row: dict, gw: int, horizon: int) -> float:
    return sum(float(row.get("per_gw", {}).get(g, 0)) for g in range(gw, gw+horizon))


def structural_candidate_ids(projections, current_ids, gw, horizon=4, per_position=8):
    """Candidate pool that preserves projection, value, and price-tier enablers."""
    current_ids = set(current_ids)
    out = set()
    for pos in (1, 2, 3, 4):
        rows = [r for r in projections if int(r["position"]) == pos and int(r["player_id"]) not in current_ids and r.get("status") not in {"i", "s", "u"}]
        by_points = sorted(rows, key=lambda r: (_future_points(r, gw, horizon), r.get("gw1", 0)), reverse=True)[:per_position]
        by_value = sorted(rows, key=lambda r: _future_points(r, gw, horizon)/max(35, float(r.get("price") or 35)), reverse=True)[:max(3, per_position//2)]
        out.update(int(r["player_id"]) for r in by_points+by_value)

        if rows:
            prices = sorted(float(r.get("price") or 0) for r in rows)
            cuts = [prices[int((len(prices)-1)*q)] for q in (0.25, 0.5, 0.75)]
            buckets = [(-1, cuts[0]), (cuts[0], cuts[1]), (cuts[1], cuts[2]), (cuts[2], 10**9)]
            for lo, hi in buckets:
                tier = [r for r in rows if lo < float(r.get("price") or 0) <= hi]
                tier.sort(key=lambda r: _future_points(r, gw, horizon), reverse=True)
                out.update(int(r["player_id"]) for r in tier[:2])
    return sorted(out)


def _single_actions(state, candidate_ids, proj_by_id, horizon, max_actions=28):
    actions = []
    owned = set(state.squad)
    for out in state.squad:
        out_row = proj_by_id[out]
        for inn in candidate_ids:
            if inn in owned or inn not in proj_by_id:
                continue
            in_row = proj_by_id[inn]
            if int(in_row["position"]) != int(out_row["position"]):
                continue
            delta = _future_points(in_row, state.gw, horizon)-_future_points(out_row, state.gw, horizon)
            actions.append((delta, Transfer(out, inn)))
    actions.sort(key=lambda x: x[0], reverse=True)
    return [a for _, a in actions[:max_actions]]


def candidate_actions(state, candidate_ids, players_by_id, proj_by_id, horizon=4, max_transfers=2, max_single_actions=28, cache: PlannerCache | None = None):
    cache_key = (state.key(), tuple(candidate_ids), int(horizon), int(max_transfers), int(max_single_actions))
    if cache is not None and cache_key in cache.actions:
        cache.action_hits += 1
        return cache.actions[cache_key]
    if cache is not None:
        cache.action_misses += 1
    actions = [tuple()]  # ROLL is always a legal candidate action.
    singles = _single_actions(state, candidate_ids, proj_by_id, horizon, max_single_actions)
    for t in singles:
        if apply_transfers(state, (t,), players_by_id, proj_by_id):
            actions.append((t,))
    if max_transfers >= 2:
        for a, b in combinations(singles, 2):
            if a.out == b.out or a.in_ == b.in_:
                continue
            pair = (a, b)
            if apply_transfers(state, pair, players_by_id, proj_by_id):
                actions.append(pair)
    if cache is not None:
        cache.actions[cache_key] = actions
    return actions


def transition(state, transfers, players_by_id, proj_by_id, bench_weight=0.2, cache: PlannerCache | None = None):
    transfers = tuple(transfers)
    transition_key = (state.key(), tuple((t.out, t.in_) for t in transfers), float(bench_weight))
    if cache is not None and transition_key in cache.transitions:
        cache.transition_hits += 1
        return cache.transitions[transition_key]
    if cache is not None:
        cache.transition_misses += 1
    applied = apply_transfers(state, transfers, players_by_id, proj_by_id)
    if applied is None:
        return None
    nxt, hit = applied
    lineup_squad = tuple(state.squad if not transfers else nxt.squad)
    lineup_key = (lineup_squad, int(state.gw), float(bench_weight))
    if cache is not None and lineup_key in cache.lineups:
        cache.lineup_hits += 1
        lineup = cache.lineups[lineup_key]
    else:
        if cache is not None:
            cache.lineup_misses += 1
        lineup = best_lineup(lineup_squad, proj_by_id, state.gw, bench_weight, selection_mode="probabilistic")
        if cache is not None:
            cache.lineups[lineup_key] = lineup
    result = Transition(nxt, transfers, hit, float(lineup["probabilistic_score"]), lineup)
    if cache is not None:
        cache.transitions[transition_key] = result
    return result


def _prune_score(path: Path):
    # Small state-value term prevents beam pruning from systematically deleting
    # a rolled FT or modest bank before its value can be realised next GW.
    return path.score + 0.35*path.state.free_transfers + 0.03*min(20, path.state.bank)


def plan_multigw(
    initial_state: ManagerState,
    players_by_id: dict,
    projections: list[dict],
    proj_by_id: dict,
    *,
    planning_horizon=4,
    candidate_per_position=8,
    beam_width=60,
    max_transfers_per_gw=2,
    bench_weight=0.2,
    discount=0.97,
    top_n=12,
    cache_enabled=True,
):
    """Beam-search sequential FPL planner.

    Unlike the V2 horizon score, this explicitly transitions FT count, bank and
    squad after every gameweek. As a result, ROLL receives value only when the
    extra transfer creates a better later path; no fixed 'roll bonus' is added.
    """
    cache = PlannerCache() if cache_enabled else None
    candidate_ids = structural_candidate_ids(
        projections, initial_state.squad, initial_state.gw,
        horizon=planning_horizon, per_position=candidate_per_position,
    )
    frontier = [Path(initial_state, 0.0, [])]
    for depth in range(planning_horizon):
        expanded = []
        for path in frontier:
            st = path.state
            actions = candidate_actions(
                st, candidate_ids, players_by_id, proj_by_id,
                horizon=max(1, planning_horizon-depth),
                max_transfers=max_transfers_per_gw,
                cache=cache,
            )
            for action in actions:
                tr = transition(st, action, players_by_id, proj_by_id, bench_weight, cache=cache)
                if tr is None:
                    continue
                gw_value = tr.lineup_score - tr.hit_cost
                score = path.score + (discount**depth)*gw_value
                step = {
                    "gw": st.gw,
                    "transfers": [x.as_dict() for x in tr.transfers],
                    "roll": not bool(tr.transfers),
                    "hit_cost": tr.hit_cost,
                    "lineup_score": round(tr.lineup_score, 2),
                    "bank_after": tr.state.bank,
                    "free_transfers_after": tr.state.free_transfers,
                    "lineup": tr.lineup,
                }
                expanded.append(Path(tr.state, score, path.steps+[step]))

        dedup = {}
        for p in sorted(expanded, key=_prune_score, reverse=True):
            key = p.state.key()
            if key not in dedup or p.score > dedup[key].score:
                dedup[key] = p
        frontier = sorted(dedup.values(), key=_prune_score, reverse=True)[:beam_width]
        if not frontier:
            break

    frontier.sort(key=lambda p: p.score, reverse=True)
    result = []
    diagnostics = cache.diagnostics() if cache is not None else {"cache_enabled": False}
    diagnostics.update({"cache_enabled": bool(cache is not None), "candidate_count": len(candidate_ids), "terminal_frontier": len(frontier), "planning_horizon": planning_horizon})
    for p in frontier[:top_n]:
        result.append({
            "score": round(p.score, 3),
            "first_action": p.steps[0] if p.steps else None,
            "steps": p.steps,
            "terminal_bank": p.state.bank,
            "terminal_free_transfers": p.state.free_transfers,
            "terminal_squad": list(p.state.squad),
            "planner_diagnostics": diagnostics,
        })
    return result
