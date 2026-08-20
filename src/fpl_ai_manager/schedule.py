
from __future__ import annotations
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from .fpl import parse_deadline

def _quiet(dt, cutoff, wake):
    h = dt.hour + dt.minute / 60
    return h >= cutoff or h < wake

def classify_window(deadline_iso, preview, final, now=None, timezone_name="Asia/Shanghai",
                    sleep_cutoff_hour=23, wake_hour=7, sleep_safe_send_hour=22):
    now = now or datetime.now(timezone.utc)
    deadline = parse_deadline(deadline_iso)
    hours = (deadline - now).total_seconds() / 3600
    tz = ZoneInfo(timezone_name)
    local_now = now.astimezone(tz)
    local_deadline = deadline.astimezone(tz)
    midpoint = sum(final) / 2
    ideal = local_deadline - timedelta(hours=midpoint)
    if _quiet(ideal, sleep_cutoff_hour, wake_hour):
        d = ideal.date()
        if ideal.hour < wake_hour:
            d -= timedelta(days=1)
        target = datetime.combine(d, time(sleep_safe_send_hour), tzinfo=tz)
        cutoff = datetime.combine(d, time(sleep_cutoff_hour), tzinfo=tz)
        if target - timedelta(minutes=30) <= local_now < cutoff:
            return "final", hours, "sleep_safe"
    elif final[0] <= hours <= final[1] and not _quiet(local_now, sleep_cutoff_hour, wake_hour):
        return "final", hours, "standard"
    if preview[0] <= hours <= preview[1]:
        return "preview", hours, "standard"
    return None, hours, None
