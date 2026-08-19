from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .analyzer import classify_window
from .fpl import FPLClient, next_event

ROOT = Path(__file__).resolve().parents[2]


def emit(name: str, value: str) -> None:
    output = os.getenv("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")
    print(f"{name}={value}")


def main() -> int:
    cfg = json.loads((ROOT / "config/manager.json").read_text())
    force = os.getenv("FORCE_REPORT", "").strip().lower()
    data = FPLClient().bootstrap()
    nxt = next_event(data["events"], datetime.now(timezone.utc))
    if not nxt:
        emit("due", "false")
        return 0
    kind, _ = classify_window(
        nxt["deadline_time"], tuple(cfg["preview_window_hours"]), tuple(cfg["final_window_hours"])
    )
    if force in {"preview", "final"}:
        kind = force
    if not kind:
        emit("due", "false")
        return 0
    gw = str(nxt["id"])
    emit("due", "true")
    emit("report_type", kind)
    emit("gw", gw)
    emit("cache_key", f"fpl-report-{gw}-{kind}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
