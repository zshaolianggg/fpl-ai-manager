from __future__ import annotations
from pathlib import Path
import json

CHIPS = ("wildcard", "freehit", "bboost", "3xc")


def derive_sell_price(purchase, current):
    if purchase is None:
        return None
    purchase, current = int(purchase), int(current)
    if current <= purchase:
        return current
    return purchase + (current - purchase) // 2


def season_start_price(player):
    """Reconstruct a player's GW1 price from current bootstrap data.

    FPL exposes prices in tenths and ``cost_change_start`` as the net movement
    since the season began, so start = current - change_since_start.
    """
    current = player.get("now_cost")
    change = player.get("cost_change_start")
    if current is None or change is None:
        return None
    return int(current) - int(change)


def permanent_transfer_purchase_prices(transfers, chips_used):
    """Return the latest verifiable permanent transfer-in price per player.

    Public picks do not expose purchase/selling prices. Public transfer history
    does expose transfer-in costs. Free Hit transactions must not alter the
    permanent purchase ledger because the original squad is restored after the
    gameweek.
    """
    freehit_events = {
        int(c["event"])
        for c in chips_used
        if c.get("name") == "freehit" and c.get("event") is not None
    }
    latest = {}
    ordered = sorted(
        transfers or [],
        key=lambda t: (int(t.get("event") or 0), str(t.get("time") or "")),
    )
    for transfer in ordered:
        event = int(transfer.get("event") or 0)
        if event in freehit_events:
            continue
        pid = transfer.get("element_in")
        cost = transfer.get("element_in_cost")
        if pid is not None and cost is not None:
            latest[int(pid)] = int(cost)
    return latest


def reconstruct_purchase_price(player_id, player, transfer_purchase_prices):
    """Reconstruct purchase basis for a player in the current permanent squad.

    If the player was bought after GW1, the latest permanent transfer-in price
    is authoritative. If there is no permanent transfer-in, the current owner
    has held the player since GW1, so the season-start price is the purchase
    basis.
    """
    pid = int(player_id)
    if pid in transfer_purchase_prices:
        return int(transfer_purchase_prices[pid]), "transfer_history"
    start = season_start_price(player)
    if start is not None:
        return int(start), "season_start_price"
    return None, None


def chip_availability(next_gw, chips_used):
    half = 1 if next_gw <= 19 else 2
    used = {c["name"]: int(c["event"]) for c in chips_used if c.get("event")}
    out = {}
    for c in CHIPS:
        ev = used.get(c)
        out[c] = not (ev and ((half == 1 and ev <= 19) or (half == 2 and ev >= 20)))
    if next_gw == 1:
        out["wildcard"] = False
        out["freehit"] = False
    if next_gw == 20 and used.get("freehit") == 19:
        out["freehit"] = False
    return out


def reconstruct_free_transfers(history_rows, chips_used, next_gw):
    """Rebuild FT state from public post-deadline history.
    GW2 begins with one FT. WC/FH preserve banked transfers; ordinary weeks consume FTs.
    """
    if next_gw <= 1:
        return None, []
    by_gw = {int(r["event"]): r for r in history_rows if r.get("event")}
    chip_by_gw = {int(c["event"]): c["name"] for c in chips_used if c.get("event")}
    start_ft = 1
    warnings = []
    for gw in range(2, next_gw):
        row = by_gw.get(gw)
        if row is None:
            warnings.append(f"Missing history row for GW{gw}; FT ledger cannot be reconciled.")
            return None, warnings
        transfers = int(row.get("event_transfers") or 0)
        cost = int(row.get("event_transfers_cost") or 0)
        if cost % 4:
            warnings.append(f"Unexpected transfer cost {cost} in GW{gw}.")
            return None, warnings
        chip = chip_by_gw.get(gw)
        if chip in {"wildcard", "freehit"}:
            end_ft = start_ft
        else:
            paid = cost // 4
            free_used = max(0, transfers - paid)
            if free_used > start_ft:
                warnings.append(f"FT reconciliation mismatch in GW{gw}.")
                return None, warnings
            end_ft = max(0, start_ft - free_used)
        start_ft = min(5, end_ft + 1)
    return start_ft, warnings


def load_public_state(client, team_id, next_gw, players_by_id):
    if next_gw == 1:
        return {
            "mode": "gw1_initial_build",
            "actionable": True,
            "squad": [],
            "bank": 1000,
            "free_transfers": None,
            "chips_available": chip_availability(1, []),
            "warnings": ["GW1 has no prior locked public squad; optimizer will build from scratch."],
        }
    entry = client.entry(team_id)
    hist = client.history(team_id)
    picks_blob = client.picks(team_id, next_gw - 1)
    picks = picks_blob.get("picks") or []
    warnings = []
    if len(picks) != 15:
        return {"mode": "managed_squad", "actionable": False, "warnings": [f"Expected 15 public picks; got {len(picks)}."]}
    bank = (picks_blob.get("entry_history") or {}).get("bank")
    if bank is None:
        bank = entry.get("last_deadline_bank")
    if bank is None:
        return {"mode": "managed_squad", "actionable": False, "warnings": ["Bank is unavailable."]}

    chips_used = hist.get("chips", [])
    try:
        public_transfers = client.transfers(team_id)
    except Exception as exc:
        public_transfers = []
        warnings.append(f"Public transfer history unavailable ({exc}); using season-start reconstruction where possible.")
    transfer_purchase = permanent_transfer_purchase_prices(public_transfers, chips_used)

    squad = []
    reconstructed = []
    for pick in picks:
        pid = int(pick["element"])
        p = players_by_id.get(pid)
        if not p:
            return {"mode": "managed_squad", "actionable": False, "warnings": [f"Player {pid} missing from bootstrap."]}
        sell = pick.get("selling_price")
        purchase = pick.get("purchase_price")
        basis = "picks"
        if purchase is None:
            purchase, basis = reconstruct_purchase_price(pid, p, transfer_purchase)
        if sell is None:
            sell = derive_sell_price(purchase, p.get("now_cost"))
        if sell is None:
            return {
                "mode": "managed_squad",
                "actionable": False,
                "warnings": warnings + [f"Cannot reconstruct selling value for {p.get('web_name', pid)} from public FPL data."],
            }
        if basis != "picks":
            reconstructed.append(f"{p.get('web_name', pid)} ({basis})")
        squad.append({
            "player_id": pid,
            "purchase_price": int(purchase) if purchase is not None else None,
            "selling_price": int(sell),
            "price_basis": basis,
            "public_position": pick.get("position"),
            "was_captain": bool(pick.get("is_captain")),
        })
    if reconstructed:
        warnings.append(
            "Purchase/selling values reconstructed from public FPL data for: "
            + ", ".join(reconstructed)
            + "."
        )

    ft, ft_warn = reconstruct_free_transfers(hist.get("current", []), chips_used, next_gw)
    warnings.extend(ft_warn)
    if ft is None:
        return {"mode": "managed_squad", "actionable": False, "warnings": warnings + ["Free-transfer ledger could not be reconciled."]}
    return {
        "mode": "managed_squad",
        "actionable": True,
        "squad": squad,
        "bank": int(bank),
        "free_transfers": int(ft),
        "chips_available": chip_availability(next_gw, chips_used),
        "chips_used": chips_used,
        "entry": {
            "id": entry.get("id"),
            "name": entry.get("name"),
            "overall_points": entry.get("summary_overall_points"),
            "overall_rank": entry.get("summary_overall_rank"),
            "last_deadline_value": entry.get("last_deadline_value"),
        },
        "warnings": warnings,
    }
