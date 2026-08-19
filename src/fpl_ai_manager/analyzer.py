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
        "expected_goals_conceded", "influence", "creativity", "threat", "ict_index",
        "status", "chance_of_playing_next_round", "news", "news_added",
        "transfers_in_event", "transfers_out_event",
    ]
    out = {k: p.get(k) for k in fields}
    out["team"] = team_name
    return out


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
