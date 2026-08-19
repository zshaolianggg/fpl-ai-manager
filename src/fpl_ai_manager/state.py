from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class StateCheck:
    squad_status: str
    squad_count: int
    squad_source: str
    bank_status: str
    bank_source: str
    free_transfers_status: str
    chips_status: str
    latest_public_gameweek: int | None
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_manual_squad_ids(manual: dict[str, Any], players: list[dict[str, Any]]) -> tuple[list[int], list[str]]:
    """Resolve optional manual squad by ids or names.

    Names are matched case-insensitively against web_name and full first/second
    name. Ambiguous or unknown names are reported instead of guessed.
    """
    warnings: list[str] = []
    ids = manual.get("squad_player_ids")
    if ids:
        return [int(x) for x in ids], warnings

    names = manual.get("squad_player_names") or []
    if not names:
        return [], warnings

    index: dict[str, list[int]] = {}
    for p in players:
        pid = int(p["id"])
        keys = {
            str(p.get("web_name") or "").strip().casefold(),
            f"{p.get('first_name', '')} {p.get('second_name', '')}".strip().casefold(),
        }
        for key in keys:
            if key:
                index.setdefault(key, []).append(pid)

    resolved: list[int] = []
    for raw in names:
        key = str(raw).strip().casefold()
        matches = index.get(key, [])
        if len(matches) == 1:
            resolved.append(matches[0])
        elif not matches:
            warnings.append(f"Manual squad player not found: {raw}")
        else:
            warnings.append(f"Manual squad player name is ambiguous: {raw}")
    return resolved, warnings


def validate_squad(ids: list[int], players_by_id: dict[int, dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    if ids and len(ids) != 15:
        warnings.append(f"Squad contains {len(ids)} players; expected 15.")
    if len(ids) != len(set(ids)):
        warnings.append("Squad contains duplicate player ids.")
    missing = [pid for pid in ids if pid not in players_by_id]
    if missing:
        warnings.append(f"Unknown player ids in squad: {missing}")
    return warnings


def build_state_check(
    *,
    squad_ids: list[int],
    squad_source: str,
    bank: Any,
    bank_source: str,
    free_transfers: Any,
    chip_history: list[dict[str, Any]],
    chips_override: Any,
    latest_public_gameweek: int | None,
    warnings: list[str],
) -> StateCheck:
    squad_ok = len(squad_ids) == 15 and len(set(squad_ids)) == 15
    notes = list(warnings)
    if latest_public_gameweek is None and squad_source == "none":
        notes.append(
            "Before the first season deadline there is no locked public picks endpoint; "
            "use config/manual_state.json to provide the draft if you want team-specific advice."
        )

    return StateCheck(
        squad_status="verified" if squad_ok else ("partial" if squad_ids else "unavailable"),
        squad_count=len(squad_ids),
        squad_source=squad_source,
        bank_status="verified" if bank is not None else "unavailable",
        bank_source=bank_source,
        free_transfers_status="manual" if free_transfers is not None else "unavailable",
        chips_status="manual" if chips_override is not None else ("history_only" if chip_history else "unavailable"),
        latest_public_gameweek=latest_public_gameweek,
        notes=notes,
    )
