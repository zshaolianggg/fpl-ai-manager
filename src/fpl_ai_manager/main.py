from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from .ai import recommend
from .analyzer import build_fixture_map, classify_window, compact_entry, compact_player, shortlist_candidates
from .emailer import send_email
from .fpl import FPLClient, FPLAPIError, latest_public_event, next_event, parse_deadline
from .state import build_state_check, resolve_manual_squad_ids, safety_warning_markdown, validate_squad

ROOT = Path(__file__).resolve().parents[2]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def collect_snapshot(cfg: dict, client: FPLClient) -> tuple[dict, str | None]:
    now = datetime.now(timezone.utc)
    team_id = int(os.getenv("FPL_TEAM_ID", cfg["team_id"]))
    bootstrap = client.bootstrap()
    fixtures = client.fixtures()
    events = bootstrap["events"]
    nxt = next_event(events, now)
    if not nxt:
        raise RuntimeError("No future FPL event/deadline found.")

    force = os.getenv("FORCE_REPORT", "").strip().lower() or None
    report_type, hours, delivery_mode = classify_window(
        nxt["deadline_time"],
        tuple(cfg["preview_window_hours"]),
        tuple(cfg["final_window_hours"]),
        now,
        timezone_name=cfg.get("timezone", "Asia/Shanghai"),
        sleep_cutoff_hour=int(cfg.get("sleep_cutoff_hour", 23)),
        wake_hour=int(cfg.get("wake_hour", 7)),
        sleep_safe_send_hour=int(cfg.get("sleep_safe_send_hour", 22)),
    )
    if force in {"preview", "final"}:
        report_type = force
        delivery_mode = "forced"
    if not report_type:
        return {"next_event": nxt, "hours_to_deadline": hours}, None

    teams = {int(t["id"]): t["name"] for t in bootstrap["teams"]}
    players_by_id = {int(p["id"]): p for p in bootstrap["elements"]}
    fixture_map = build_fixture_map(fixtures, teams, int(nxt["id"]), int(cfg["lookahead_gameweeks"]))

    entry = {}
    history = {}
    picks_data = {}
    warnings = []
    try:
        entry = client.entry(team_id)
    except FPLAPIError as e:
        warnings.append(str(e))
    try:
        history = client.history(team_id)
    except FPLAPIError as e:
        warnings.append(str(e))

    public_gw = latest_public_event(events, now)
    if public_gw:
        try:
            picks_data = client.picks(team_id, public_gw)
        except FPLAPIError as e:
            warnings.append(str(e))

    manual_path = ROOT / cfg.get("manual_state_file", "config/manual_state.json")
    manual = load_json(manual_path)
    if not manual.get("enabled"):
        manual = {}

    manual_ids, manual_warnings = resolve_manual_squad_ids(manual, bootstrap["elements"])
    warnings.extend(manual_warnings)
    public_ids = [int(p.get("element")) for p in picks_data.get("picks", []) if p.get("element") is not None]
    if manual_ids:
        squad_ids = manual_ids
        squad_source = "manual_override"
    elif public_ids:
        squad_ids = public_ids
        squad_source = f"public_locked_gw_{public_gw}"
    else:
        squad_ids = []
        squad_source = "none"
    warnings.extend(validate_squad(squad_ids, players_by_id))
    squad = []
    for pid in squad_ids:
        if pid in players_by_id:
            p = players_by_id[pid]
            squad.append({**compact_player(p, teams[int(p["team"])]), "fixtures": fixture_map.get(teams[int(p["team"])], [])})

    latest_hist = history.get("current", [])[-1] if history.get("current") else {}
    if manual.get("bank_tenths") is not None:
        bank = manual.get("bank_tenths")
        bank_source = "manual_override"
    else:
        bank = latest_hist.get("bank")
        bank_source = f"public_history_gw_{public_gw}" if bank is not None else "none"
    value = manual.get("team_value_tenths") if manual.get("team_value_tenths") is not None else latest_hist.get("value")

    candidate_pool = shortlist_candidates(bootstrap["elements"], teams)

    local_tz = ZoneInfo(cfg.get("timezone", "Asia/Singapore"))
    state_check = build_state_check(
        squad_ids=squad_ids,
        squad_source=squad_source,
        bank=bank,
        bank_source=bank_source,
        free_transfers=manual.get("free_transfers"),
        chip_history=history.get("chips", []),
        chips_override=manual.get("chips_available"),
        latest_public_gameweek=public_gw,
        warnings=warnings,
    )

    mode = "gw1_initial_build" if int(nxt["id"]) == 1 and not squad_ids else "managed_squad"

    state_dict = state_check.to_dict()
    if mode == "gw1_initial_build":
        # Pre-GW1 is intentionally draft-from-scratch mode, so remove safety
        # diagnostics that only apply to managed-squad transfer advice.
        state_dict["notes"] = [
            n for n in state_dict.get("notes", [])
            if "Safety gate failed" not in n
            and "use config/manual_state.json" not in n
        ]

    payload = {
        "mode": mode,
        "report_type": report_type,
        "delivery_mode": delivery_mode,
        "generated_at": now.isoformat(),
        "team_id": team_id,
        "objective": cfg["objective"],
        "risk_profile": cfg["risk_profile"],
        "next_gameweek": int(nxt["id"]),
        "deadline_utc": nxt["deadline_time"],
        "deadline_local": parse_deadline(nxt["deadline_time"]).astimezone(local_tz).isoformat(),
        "hours_to_deadline": round(hours, 2),
        "entry_summary": compact_entry(entry),
        "state_check": state_dict,
        "latest_public_gameweek": public_gw,
        "latest_history": latest_hist,
        "bank_tenths": bank,
        "team_value_tenths": value,
        "free_transfers": manual.get("free_transfers"),
        "chips_available_override": manual.get("chips_available"),
        "chip_history": history.get("chips", []),
        "current_public_squad": squad,
        "team_fixtures": fixture_map,
        "candidate_pool": candidate_pool,
        "data_warnings": state_check.notes + [
            "Public FPL endpoints may not expose transfers/captain changes made after the last deadline. Recommendations are based on the latest public squad unless manual_state.json overrides it.",
            "Free-transfer count and exact currently available chips may not be inferable from public data; do not guess when absent."
        ],
    }
    return payload, report_type


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "config/manager.json"))
    parser.add_argument("--print-snapshot", action="store_true")
    args = parser.parse_args()
    cfg = load_json(Path(args.config))
    snapshot, report_type = collect_snapshot(cfg, FPLClient())
    if not report_type:
        print(f"No report due. Hours to next deadline: {snapshot['hours_to_deadline']:.2f}")
        return 0

    if args.print_snapshot:
        print(json.dumps(snapshot, indent=2, default=str))
        return 0

    state = snapshot.get("state_check", {})
    gw = snapshot["next_gameweek"]
    mode = snapshot.get("mode", "managed_squad")
    if mode == "gw1_initial_build":
        text = recommend(snapshot)
        subject = f"FPL GW1 - {'Initial Squad Preview' if report_type == 'preview' else ('Sleep-safe Final Initial Squad' if snapshot.get('delivery_mode') == 'sleep_safe' else 'Final Initial Squad')}"
    elif not state.get("actionable", False):
        text = safety_warning_markdown(snapshot)
        subject = f"FPL GW{gw} - ACTION WITHHELD (state not verified)"
    else:
        text = recommend(snapshot)
        subject = f"FPL GW{gw} - {'24h Preview' if report_type == 'preview' else ('Sleep-safe Final Recommendation' if snapshot.get('delivery_mode') == 'sleep_safe' else 'Final Recommendation')}"
    print(text)
    if os.getenv("DRY_RUN", "false").lower() not in {"1", "true", "yes"}:
        send_email(subject, text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
