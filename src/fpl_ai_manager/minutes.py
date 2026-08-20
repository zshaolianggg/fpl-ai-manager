
from __future__ import annotations
from datetime import datetime, timezone
from .news import news_minutes_factor

def _num(x, default=0.0):
    try: return float(x)
    except (TypeError, ValueError): return default

def expected_minutes(player, history, prior_understat, news_index, congestion_days=None):
    recent = list(history or [])[-5:]
    confidence = "LOW"
    if recent:
        weights = [0.10,0.12,0.18,0.25,0.35][-len(recent):]
        vals = [_num(r.get("minutes")) for r in recent]
        w = weights[-len(vals):]
        base = sum(a*b for a,b in zip(vals,w)) / sum(w)
        starts = sum(v >= 45 for v in vals) / len(vals)
        base = 0.72*base + 0.28*(90*starts)
        confidence = "MEDIUM" if len(recent) >= 3 else "LOW"
    else:
        pmins = _num((prior_understat or {}).get("time"))
        apps = _num((prior_understat or {}).get("games"))
        if apps > 0:
            base = min(88.0, pmins/apps)
            confidence = "LOW"
        else:
            pos = int(player.get("element_type") or 0)
            base = {1:86,2:78,3:74,4:72}.get(pos,72)

    status = player.get("status")
    chance = player.get("chance_of_playing_next_round")
    if status in {"i","s","u"}:
        base *= 0.10
    elif chance is not None:
        base *= max(0, min(1, _num(chance)/100))

    nf, news_conf = news_minutes_factor(player.get("web_name",""), news_index)
    base *= nf
    if news_conf == "HIGH":
        confidence = "HIGH" if nf in {0.0,1.0,1.05} else "MEDIUM"
    elif news_conf == "MEDIUM" and confidence == "LOW":
        confidence = "MEDIUM"

    if congestion_days is not None and congestion_days < 4:
        base *= 0.93

    return round(max(0.0,min(90.0,base)),1), confidence
