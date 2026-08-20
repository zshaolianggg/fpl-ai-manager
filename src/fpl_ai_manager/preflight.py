
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import json, os
from .fpl import FPLClient,next_event,parse_deadline
from .schedule import classify_window
from .report_state import load,gw_state

ROOT=Path(__file__).resolve().parents[2]
def emit(k,v):
    out=os.getenv("GITHUB_OUTPUT")
    if out:
        with open(out,"a") as f:f.write(f"{k}={v}\n")
    else: print(f"{k}={v}")

def main():
    cfg=json.loads((ROOT/"config/manager.json").read_text())
    force=os.getenv("FORCE_REPORT","").strip().lower()
    b=FPLClient().bootstrap(); nxt=next_event(b["events"])
    if not nxt: emit("due","false"); return 0
    gw=int(nxt["id"])
    kind,hours,delivery=classify_window(nxt["deadline_time"],tuple(cfg["preview_window_hours"]),tuple(cfg["final_window_hours"]),
        timezone_name=cfg["timezone"],sleep_cutoff_hour=cfg["sleep_cutoff_hour"],wake_hour=cfg["wake_hour"],sleep_safe_send_hour=cfg["sleep_safe_send_hour"])
    if force in {"preview","final"}:
        kind=force; delivery="forced"
    else:
        g=gw_state(load(),gw)
        if kind and g.get(f"{kind}_sent_at"):
            kind=None
        # One exceptional late check after a final; it emails only if material news changed.
        if not kind and g.get("final_sent_at") and not g.get("late_check_done_at") and 0.50 <= hours <= 1.50:
            kind="late_check"; delivery="late_material_only"
    if not kind: emit("due","false"); return 0
    emit("due","true"); emit("report_type",kind); emit("gw",gw); emit("delivery_mode",delivery or "standard")
    return 0
if __name__=="__main__": raise SystemExit(main())
