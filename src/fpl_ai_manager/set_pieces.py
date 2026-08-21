from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class SetPieceRole:
    penalty_share: float = 0.0
    corner_share: float = 0.0
    indirect_fk_share: float = 0.0
    direct_fk_share: float = 0.0


def infer_set_piece_role(player: dict) -> SetPieceRole:
    """Best-effort role extraction from public FPL fields when present.

    The FPL bootstrap is not guaranteed to expose set-piece shares. Keeping this
    adapter explicit lets a richer provider be added later without contaminating
    projection code with source-specific assumptions.
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
        return 0.0

    return SetPieceRole(
        penalty_share=share("penalty_share", "penalties_order"),
        corner_share=share("corner_share"),
        indirect_fk_share=share("indirect_freekick_share"),
        direct_fk_share=share("direct_freekick_share"),
    )
