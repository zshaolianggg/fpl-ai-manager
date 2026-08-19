from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .fpl import parse_deadline


def classify_window(deadline_iso: str, preview: tuple[float, float], final: tuple[float, float], now: datetime | None = None) -> tuple[str | None, float]:
    now = now or datetime.now(timezone.utc)
    deadline = parse_deadline(deadline_iso)
    hours = (deadline - now).total_seconds() / 3600
    if final[0] <= hours <= final[1]:
        return "final", hours
    if preview[0] <= hours <= preview[1]:
        return "preview", hours
    return None, hours


def compact_player(p: dict[str, Any], team_name: str) -> dict[str, Any]:
    fields = [
        "id", "web_name", "element_type", "now_cost", "total_points", "event_points",
        "form", "points_per_game", "selected_by_percent", "minutes", "starts",
        "expected_goals", "expected_assists", "expected_goal_involvements",
        "status", "chance_of_playing_next_round", "news",
    ]
    out = {k: p.get(k) for k in fields}
    out["team"] = team_name
    return out


def candidate_player(p: dict[str, Any], team_name: str) -> dict[str, Any]:
    """Smaller representation for transfer candidates.

    Fixtures are intentionally not embedded here; they are supplied once in
    team_fixtures to avoid repeating the same data for every player.
    """
    fields = [
        "id", "web_name", "element_type", "now_cost", "total_points", "form",
        "points_per_game", "selected_by_percent", "minutes", "starts",
        "expected_goal_involvements", "status", "chance_of_playing_next_round", "news",
    ]
    out = {k: p.get(k) for k in fields}
    out["team"] = team_name
    return out


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def candidate_score(p: dict[str, Any]) -> float:
    """Ranking heuristic used only to choose which candidates reach the LLM.

    It is deliberately broad: season points/form/xGI matter once data exists,
    while ownership helps keep relevant options in the pool at the start of a
    new season when most performance fields are still zero.
    """
    availability = 0.0 if p.get("status") in {"i", "s", "u"} else 1.0
    return (
        2.0 * _num(p.get("form"))
        + 1.2 * _num(p.get("points_per_game"))
        + 0.03 * _num(p.get("total_points"))
        + 1.5 * _num(p.get("expected_goal_involvements"))
        + 0.08 * _num(p.get("selected_by_percent"))
        + availability
    )


def shortlist_candidates(players: list[dict[str, Any]], teams: dict[int, str]) -> list[dict[str, Any]]:
    # Enough breadth for sensible alternatives without sending the entire game
    # database. FPL position ids: 1 GK, 2 DEF, 3 MID, 4 FWD.
    limits = {1: 18, 2: 40, 3: 45, 4: 30}
    result: list[dict[str, Any]] = []
    for position, limit in limits.items():
        group = [p for p in players if int(p.get("element_type", 0)) == position]
        group.sort(key=candidate_score, reverse=True)
        for p in group[:limit]:
            result.append(candidate_player(p, teams[int(p["team"])]))
    return result


def compact_entry(entry: dict[str, Any]) -> dict[str, Any]:
    fields = [
        "id", "name", "player_first_name", "player_last_name",
        "summary_overall_points", "summary_overall_rank",
        "summary_event_points", "summary_event_rank",
        "last_deadline_bank", "last_deadline_value", "last_deadline_total_transfers",
    ]
    return {k: entry.get(k) for k in fields if k in entry}


def build_fixture_map(fixtures: list[dict[str, Any]], teams: dict[int, str], next_event_id: int, lookahead: int) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    max_event = next_event_id + lookahead - 1
    for f in fixtures:
        ev = f.get("event")
        if not ev or not (next_event_id <= int(ev) <= max_event):
            continue
        home, away = int(f["team_h"]), int(f["team_a"])
        result.setdefault(teams[home], []).append({
            "gw": ev, "opponent": teams[away], "venue": "H", "difficulty": f.get("team_h_difficulty"),
            "kickoff_time": f.get("kickoff_time"),
        })
        result.setdefault(teams[away], []).append({
            "gw": ev, "opponent": teams[home], "venue": "A", "difficulty": f.get("team_a_difficulty"),
            "kickoff_time": f.get("kickoff_time"),
        })
    for value in result.values():
        value.sort(key=lambda x: (x["gw"], x.get("kickoff_time") or ""))
    return result
