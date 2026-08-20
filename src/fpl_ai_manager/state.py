
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
            "warnings": ["GW1 has no prior locked public squad; optimizer will build from scratch."]
        }
    entry = client.entry(team_id)
    hist = client.history(team_id)
    picks_blob = client.picks(team_id, next_gw - 1)
    picks = picks_blob.get("picks") or []
    warnings = []
    if len(picks) != 15:
        return {"mode":"managed_squad","actionable":False,"warnings":[f"Expected 15 public picks; got {len(picks)}."]}
    bank = (picks_blob.get("entry_history") or {}).get("bank")
    if bank is None:
        bank = entry.get("last_deadline_bank")
    if bank is None:
        return {"mode":"managed_squad","actionable":False,"warnings":["Bank is unavailable."]}
    squad = []
    for pick in picks:
        pid = int(pick["element"])
        p = players_by_id.get(pid)
        if not p:
            return {"mode":"managed_squad","actionable":False,"warnings":[f"Player {pid} missing from bootstrap."]}
        sell = pick.get("selling_price")
        purchase = pick.get("purchase_price")
        if sell is None:
            sell = derive_sell_price(purchase, p.get("now_cost"))
        if sell is None:
            return {"mode":"managed_squad","actionable":False,"warnings":[f"Cannot verify selling value for {p.get('web_name', pid)}."]}
        squad.append({
            "player_id": pid,
            "purchase_price": purchase,
            "selling_price": int(sell),
            "public_position": pick.get("position"),
            "was_captain": bool(pick.get("is_captain")),
        })
    ft, ft_warn = reconstruct_free_transfers(hist.get("current", []), hist.get("chips", []), next_gw)
    warnings.extend(ft_warn)
    if ft is None:
        return {"mode":"managed_squad","actionable":False,"warnings":warnings + ["Free-transfer ledger could not be reconciled."]}
    return {
        "mode":"managed_squad",
        "actionable":True,
        "squad":squad,
        "bank":int(bank),
        "free_transfers":int(ft),
        "chips_available":chip_availability(next_gw, hist.get("chips", [])),
        "chips_used":hist.get("chips", []),
        "entry": {
            "id": entry.get("id"),
            "name": entry.get("name"),
            "overall_points": entry.get("summary_overall_points"),
            "overall_rank": entry.get("summary_overall_rank"),
            "last_deadline_value": entry.get("last_deadline_value"),
        },
        "warnings":warnings
    }
