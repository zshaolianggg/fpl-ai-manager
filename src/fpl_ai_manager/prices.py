from __future__ import annotations


def projected_price(row: dict, gw: int) -> int:
    """Return the modeled market price (FPL tenths) for a future GW.

    A future price model may populate ``price_path`` as {gw: price}. Until a
    calibrated source exists, the current official price is the neutral
    fallback. This makes the planner price-path aware without inventing moves.
    """
    path = row.get("price_path") or {}
    if gw in path:
        return int(path[gw])
    if str(gw) in path:
        return int(path[str(gw)])
    return int(row.get("price") or 0)


def projected_sell_price(purchase_price: int | None, current_price: int, fallback_sell: int | None = None) -> int:
    """Apply FPL's profit-sharing selling-price rule to a projected price."""
    if purchase_price is None:
        return int(fallback_sell if fallback_sell is not None else current_price)
    purchase = int(purchase_price)
    current = int(current_price)
    if current <= purchase:
        return current
    return purchase + (current - purchase) // 2


def price_risk(row: dict, gw: int) -> dict:
    """Read optional, bounded future price-risk metadata.

    Alpha 4 deliberately does not manufacture a price forecast. External or
    later calibrated sources can provide ``price_risk`` entries; otherwise the
    result is neutral.
    """
    risk = row.get("price_risk") or {}
    item = risk.get(gw, risk.get(str(gw), {})) if isinstance(risk, dict) else {}
    try:
        rise_probability = max(0.0, min(1.0, float(item.get("rise_probability", 0.0))))
        adverse_delta = max(0, int(item.get("adverse_delta", 0)))
    except (TypeError, ValueError):
        rise_probability, adverse_delta = 0.0, 0
    return {"rise_probability": rise_probability, "adverse_delta": adverse_delta}


def affordability_risk_for_buys(rows: list[dict], gw: int, bank_after: int) -> dict:
    expected_adverse = 0.0
    max_adverse = 0
    exposed = []
    for row in rows:
        r = price_risk(row, gw)
        if r["adverse_delta"] <= 0 or r["rise_probability"] <= 0:
            continue
        expected_adverse += r["rise_probability"] * r["adverse_delta"]
        max_adverse += r["adverse_delta"]
        exposed.append(int(row["player_id"]))
    return {
        "bank_after": int(bank_after),
        "expected_adverse_tenths": round(expected_adverse, 3),
        "max_adverse_tenths": int(max_adverse),
        "at_risk": bool(exposed and bank_after < max_adverse),
        "exposed_player_ids": exposed,
    }
