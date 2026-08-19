from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
import requests

BASE = "https://fantasy.premierleague.com/api"


class FPLAPIError(RuntimeError):
    pass


@dataclass
class FPLClient:
    timeout: int = 20

    def get(self, path: str) -> Any:
        url = f"{BASE}/{path.lstrip('/')}"
        try:
            r = requests.get(url, timeout=self.timeout, headers={"User-Agent": "fpl-ai-manager/1.0"})
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            raise FPLAPIError(f"FPL request failed for {url}: {exc}") from exc

    def bootstrap(self) -> dict[str, Any]:
        return self.get("bootstrap-static/")

    def fixtures(self) -> list[dict[str, Any]]:
        return self.get("fixtures/")

    def entry(self, team_id: int) -> dict[str, Any]:
        return self.get(f"entry/{team_id}/")

    def history(self, team_id: int) -> dict[str, Any]:
        return self.get(f"entry/{team_id}/history/")

    def picks(self, team_id: int, event_id: int) -> dict[str, Any]:
        return self.get(f"entry/{team_id}/event/{event_id}/picks/")


def parse_deadline(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def next_event(events: list[dict[str, Any]], now: datetime | None = None) -> dict[str, Any] | None:
    now = now or datetime.now(timezone.utc)
    future = [e for e in events if e.get("deadline_time") and parse_deadline(e["deadline_time"]) > now]
    return min(future, key=lambda e: parse_deadline(e["deadline_time"])) if future else None


def latest_public_event(events: list[dict[str, Any]], now: datetime | None = None) -> int | None:
    now = now or datetime.now(timezone.utc)
    candidates = [e for e in events if e.get("deadline_time") and parse_deadline(e["deadline_time"]) <= now]
    return max((int(e["id"]) for e in candidates), default=None)
