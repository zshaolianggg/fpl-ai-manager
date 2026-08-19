from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from .ai import recommend
from .analyzer import build_fixture_map, classify_window, compact_player
from .emailer import send_email
from .fpl import FPLClient, FPLAPIError, latest_public_event, next_event, parse_deadline

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
    report_type, hours = classify_window(
        nxt["deadline_time"], tuple(cfg["preview_window_hours"]), tuple(cfg["final_window_hours"]), now
    )
    if force in {"preview", "final"}:
        report_type = force
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

    squad_ids = manual.get("squad_player_ids") or [p.get("element") for p in picks_data.get("picks", [])]
    squad = []
    for pid in squad_ids:
        if pid in players_by_id:
            p = players_by_id[pid]
            squad.append({**compact_player(p, teams[int(p["team"])]), "fixtures": fixture_map.get(teams[int(p["team"])], [])})

    latest_hist = history.get("current", [])[-1] if history.get("current") else {}
    bank = manual.get("bank_tenths") if manual.get("bank_tenths") is not None else latest_hist.get("bank")
    value = latest_hist.get("value")

    all_players = []
    for p in bootstrap["elements"]:
        team_name = teams[int(p["team"])]
        cp = compact_player(p, team_name)
        cp["fixtures"] = fixture_map.get(team_name, [])
        all_players.append(cp)

    local_tz = ZoneInfo(cfg.get("timezone", "Asia/Singapore"))
    payload = {
        "report_type": report_type,
        "generated_at": now.isoformat(),
        "team_id": team_id,
        "objective": cfg["objective"],
        "risk_profile": cfg["risk_profile"],
        "next_gameweek": int(nxt["id"]),
        "deadline_utc": nxt["deadline_time"],
        "deadline_local": parse_deadline(nxt["deadline_time"]).astimezone(local_tz).isoformat(),
        "hours_to_deadline": round(hours, 2),
        "entry_summary": entry,
        "latest_public_gameweek": public_gw,
        "latest_history": latest_hist,
        "bank_tenths": bank,
        "team_value_tenths": value,
        "free_transfers": manual.get("free_transfers"),
        "chips_available_override": manual.get("chips_available"),
        "chip_history": history.get("chips", []),
        "current_public_squad": squad,
        "candidate_pool": all_players,
        "data_warnings": warnings + [
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

    text = recommend(snapshot)
    gw = snapshot["next_gameweek"]
    subject = f"FPL GW{gw} - {'24h Preview' if report_type == 'preview' else 'Final Recommendation'}"
    print(text)
    if os.getenv("DRY_RUN", "false").lower() not in {"1", "true", "yes"}:
        send_email(subject, text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
