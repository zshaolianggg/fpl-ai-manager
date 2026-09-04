from __future__ import annotations
from dataclasses import dataclass

from .stats import norm_name


def _num(x, default=0.0):
    try: return float(x)
    except (TypeError, ValueError): return default


@dataclass(frozen=True)
class SetPieceRole:
    penalty_share: float = 0.0
    corner_share: float = 0.0
    indirect_fk_share: float = 0.0
    direct_fk_share: float = 0.0
    is_penalty_taker: bool = False
    penalty_goals_current_season: float = 0.0


def _fpl_declared_share(player):
    """FPL bootstrap does not reliably expose set-piece share fields today.

    Kept as the preferred source if a future bootstrap payload adds them, so a
    richer provider can be swapped in without touching projection code.
    """
    def share(*keys):
        for key in keys:
            value = player.get(key)
            try:
                if value is not None:
                    v = float(value)
                    return max(0.0, min(1.0, v if v <= 1 else v / 100.0))
            except (TypeError, ValueError):
                pass
        return None
    return {
        "penalty_share": share("penalty_share", "penalties_order"),
        "corner_share": share("corner_share"),
        "indirect_fk_share": share("indirect_freekick_share"),
        "direct_fk_share": share("direct_freekick_share"),
    }


def penalty_goals_current_season(player, understat_current):
    """Empirical current-season penalty goals from Understat (goals - npg).

    Understat's plain ``goals``/``npg`` season totals let us isolate penalty
    conversions without any dedicated penalty-taker feed: ``npg`` already
    excludes penalties, so the difference is penalty goals scored.
    """
    row = (understat_current or {}).get(norm_name(player.get("web_name")))
    if not row:
        return 0.0
    return max(0.0, _num(row.get("goals"))-_num(row.get("npg")))


def infer_set_piece_role(player: dict, understat_current: dict | None = None, team_penalty_goals: dict | None = None) -> SetPieceRole:
    """Best-effort penalty-taker role, preferring a real FPL field when present
    and otherwise inferring it from Understat's current-season goal split.

    Corner/free-kick shares have no reliable free data source and remain zero
    until a richer provider is available.
    """
    declared = _fpl_declared_share(player)
    pen_goals = penalty_goals_current_season(player, understat_current or {})
    team_total = float((team_penalty_goals or {}).get(int(player.get("team") or 0), 0.0))
    inferred_share = (pen_goals/team_total) if team_total > 0 else (1.0 if pen_goals >= 1 else 0.0)
    penalty_share = declared["penalty_share"] if declared["penalty_share"] is not None else inferred_share
    # Require a clear team-relative majority (or sole data point) before
    # treating a player as the confirmed taker; a single opportunistic goal on
    # a team with several penalty scorers is not enough evidence of the role.
    is_taker = pen_goals >= 1.0 and penalty_share >= 0.5

    return SetPieceRole(
        penalty_share=penalty_share,
        corner_share=declared["corner_share"] or 0.0,
        indirect_fk_share=declared["indirect_fk_share"] or 0.0,
        direct_fk_share=declared["direct_fk_share"] or 0.0,
        is_penalty_taker=is_taker,
        penalty_goals_current_season=pen_goals,
    )
