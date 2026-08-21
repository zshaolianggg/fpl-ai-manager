from __future__ import annotations
from dataclasses import dataclass
from math import exp


@dataclass(frozen=True)
class TeamStrength:
    team_id: int
    attack_home: float = 1.0
    attack_away: float = 1.0
    defence_home: float = 1.0
    defence_away: float = 1.0


@dataclass(frozen=True)
class FixtureExpectation:
    home_xg: float
    away_xg: float
    home_cs_probability: float
    away_cs_probability: float


def _positive(value, default=1.0):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def build_team_strengths(team_rows: list[dict] | None) -> dict[int, TeamStrength]:
    """Normalize official FPL attack/defence strength fields around league average.

    FPL strength fields are relative ratings, not xG. We use them only as a
    stable team-strength prior and convert the matchup to expected goals below.
    Missing fields degrade to a neutral 1.0 rating.
    """
    rows = list(team_rows or [])
    if not rows:
        return {}

    fields = (
        "strength_attack_home", "strength_attack_away",
        "strength_defence_home", "strength_defence_away",
    )
    means = {}
    for field in fields:
        vals = [_positive(r.get(field), 0.0) for r in rows]
        vals = [v for v in vals if v > 0]
        means[field] = sum(vals) / len(vals) if vals else 1.0

    out = {}
    for row in rows:
        tid = int(row["id"])
        out[tid] = TeamStrength(
            team_id=tid,
            attack_home=_positive(row.get("strength_attack_home")) / means["strength_attack_home"],
            attack_away=_positive(row.get("strength_attack_away")) / means["strength_attack_away"],
            # Higher FPL defence strength means a better defence, so the ratio
            # remains >1 for stronger teams and is inverted in the matchup.
            defence_home=_positive(row.get("strength_defence_home")) / means["strength_defence_home"],
            defence_away=_positive(row.get("strength_defence_away")) / means["strength_defence_away"],
        )
    return out


def fixture_expectation(
    home_team_id: int,
    away_team_id: int,
    strengths: dict[int, TeamStrength],
    league_home_xg: float = 1.55,
    league_away_xg: float = 1.25,
) -> FixtureExpectation:
    home = strengths.get(int(home_team_id), TeamStrength(int(home_team_id)))
    away = strengths.get(int(away_team_id), TeamStrength(int(away_team_id)))

    home_xg = league_home_xg * home.attack_home / max(0.55, away.defence_away)
    away_xg = league_away_xg * away.attack_away / max(0.55, home.defence_home)

    # Guard against extreme official ratings early in a season.
    home_xg = max(0.20, min(3.80, home_xg))
    away_xg = max(0.15, min(3.50, away_xg))
    return FixtureExpectation(
        home_xg=home_xg,
        away_xg=away_xg,
        home_cs_probability=exp(-away_xg),
        away_cs_probability=exp(-home_xg),
    )
