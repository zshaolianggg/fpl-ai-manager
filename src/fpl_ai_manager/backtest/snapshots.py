from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json

class LeakageError(ValueError):
    pass

def _dt(value):
    if value is None or value == "": return None
    if isinstance(value, datetime): return value
    return datetime.fromisoformat(str(value).replace("Z","+00:00"))

def validate_no_future_leakage(snapshot: dict) -> None:
    """Reject evidence timestamped after the recorded decision deadline.

    Snapshot producers should put externally observed facts in ``evidence`` with
    an ``observed_at``/``published_at``/``timestamp`` field. This guard is kept
    deliberately generic so new evidence sources inherit the same rule.
    """
    deadline=_dt(snapshot.get("deadline"))
    if deadline is None:
        raise LeakageError("snapshot deadline is required")
    if deadline.tzinfo is None:
        deadline=deadline.replace(tzinfo=timezone.utc)
    for item in snapshot.get("evidence", []) or []:
        stamp=item.get("observed_at") or item.get("published_at") or item.get("timestamp")
        dt=_dt(stamp)
        if dt is None: continue
        if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
        if dt > deadline:
            raise LeakageError(f"future evidence after deadline: {stamp}")

def write_snapshot(path, snapshot: dict) -> Path:
    validate_no_future_leakage(snapshot)
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(snapshot,indent=2,default=str),encoding="utf-8")
    return p
