
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone, timedelta
import html, json, re, requests, unicodedata

def norm_name(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "", s)

class UnderstatProvider:
    name = "understat"
    def __init__(self, cache_dir=".cache", cache_hours=8):
        self.cache_dir = Path(cache_dir)
        self.cache_hours = cache_hours
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, season):
        return self.cache_dir / f"understat-epl-{season}.json"

    def _fresh(self, p):
        if not p.exists(): return False
        age = datetime.now(timezone.utc).timestamp() - p.stat().st_mtime
        return age < self.cache_hours * 3600

    def _fetch_page(self, season):
        url = f"https://understat.com/league/EPL/{int(season)}"
        r = requests.get(url, timeout=20, headers={"User-Agent":"Mozilla/5.0 fpl-ai-manager"})
        r.raise_for_status()
        return r.text

    def _extract_js_var(self, text, var_name):
        m = re.search(var_name + r"\s*=\s*JSON\.parse\('(.+?)'\)", text)
        if not m:
            return None
        raw = bytes(m.group(1), "utf-8").decode("unicode_escape")
        return json.loads(raw)

    def _load_combined(self, season):
        p = self._path(season)
        if self._fresh(p):
            cached = json.loads(p.read_text())
            if isinstance(cached, dict) and "players" in cached:
                return cached
            # Legacy players-only cache format; refetch so team data can populate.
        text = self._fetch_page(season)
        players = self._extract_js_var(text, "playersData")
        if players is None:
            raise RuntimeError("Understat playersData was not found.")
        teams = self._extract_js_var(text, "teamsData") or {}
        combined = {"players": players, "teams": teams}
        p.write_text(json.dumps(combined))
        return combined

    def season(self, season):
        return self._load_combined(season)["players"]

    def teams(self, season):
        return self._load_combined(season)["teams"]

def index_understat(rows):
    out = {}
    for r in rows:
        key = norm_name(r.get("player_name"))
        if key:
            out[key] = r
    return out

def load_external_stats(cfg, current_season_start=2026):
    warnings = []
    if not cfg.get("understat_enabled", True):
        return {"current":{}, "prior":{}, "current_teams":{}, "prior_teams":{}, "provider":"disabled"}, warnings
    provider = UnderstatProvider(cfg.get("cache_dir", ".cache"), cfg.get("cache_hours", 8))
    current, prior = {}, {}
    current_teams, prior_teams = {}, {}
    try:
        current = index_understat(provider.season(current_season_start))
        current_teams = provider.teams(current_season_start)
    except Exception as exc:
        warnings.append(f"Understat current-season unavailable; FPL-only fallback active: {exc}")
    try:
        prior = index_understat(provider.season(current_season_start - 1))
        prior_teams = provider.teams(current_season_start - 1)
    except Exception as exc:
        warnings.append(f"Understat prior-season unavailable: {exc}")
    return {
        "current":current, "prior":prior, "current_teams":current_teams, "prior_teams":prior_teams,
        "provider":"understat" if (current or prior) else "fpl_only",
    }, warnings
