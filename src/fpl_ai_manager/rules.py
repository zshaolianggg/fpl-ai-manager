from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class ScoringRules:
    season: str
    goal_points: dict[int, int]
    assist_points: int
    clean_sheet_points: dict[int, int]
    defensive_contribution_points: int
    defensive_contribution_thresholds: dict[int, int]
    save_threshold: int
    save_points: int
    yellow_card_points: int = -1
    red_card_points: int = -3
    own_goal_points: int = -2
    penalty_miss_points: int = -2
    penalty_save_points: int = 5


_RULES = {
    "2026/27": ScoringRules(
        season="2026/27",
        goal_points={1: 10, 2: 6, 3: 5, 4: 4},
        assist_points=3,
        clean_sheet_points={1: 4, 2: 4, 3: 1, 4: 0},
        defensive_contribution_points=2,
        defensive_contribution_thresholds={2: 10, 3: 12, 4: 12},
        save_threshold=3,
        save_points=1,
    ),
}


def rules_for_season(season: str = "2026/27") -> ScoringRules:
    try:
        return _RULES[season]
    except KeyError as exc:
        raise ValueError(f"Unsupported FPL scoring season: {season}") from exc


def season_start_year(season: str) -> int:
    try:
        return int(str(season).split("/", 1)[0])
    except (TypeError, ValueError, IndexError) as exc:
        raise ValueError(f"Invalid season string: {season!r}") from exc
