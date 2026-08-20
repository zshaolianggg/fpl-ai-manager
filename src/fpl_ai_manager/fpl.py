
from __future__ import annotations
from datetime import datetime, timezone
import time
import requests

BASE = "https://fantasy.premierleague.com/api"

class FPLAPIError(RuntimeError):
    pass

def parse_deadline(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)

def next_event(events, now=None):
    now = now or datetime.now(timezone.utc)
    future = [e for e in events if e.get("deadline_time") and parse_deadline(e["deadline_time"]) > now]
    return min(future, key=lambda e: parse_deadline(e["deadline_time"])) if future else None

class FPLClient:
    def __init__(self, timeout=20):
        self.timeout = timeout
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": "fpl-ai-manager/2.0"})

    def _get(self, path, retries=3):
        url = f"{BASE}/{path.lstrip('/')}"
        last = None
        for attempt in range(retries):
            try:
                r = self.s.get(url, timeout=self.timeout)
                if r.status_code == 429:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r.json()
            except Exception as exc:
                last = exc
                time.sleep(0.5 * (attempt + 1))
        raise FPLAPIError(f"GET {url} failed: {last}")

    def bootstrap(self): return self._get("bootstrap-static/")
    def fixtures(self): return self._get("fixtures/")
    def entry(self, team_id): return self._get(f"entry/{int(team_id)}/")
    def history(self, team_id): return self._get(f"entry/{int(team_id)}/history/")
    def picks(self, team_id, gw): return self._get(f"entry/{int(team_id)}/event/{int(gw)}/picks/")
    def transfers(self, team_id): return self._get(f"entry/{int(team_id)}/transfers/")
    def element_summary(self, player_id): return self._get(f"element-summary/{int(player_id)}/")
    def league_standings(self, league_id, page=1):
        return self._get(f"leagues-classic/{int(league_id)}/standings/?page_standings={int(page)}")
