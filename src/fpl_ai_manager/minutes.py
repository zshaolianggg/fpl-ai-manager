from __future__ import annotations
from dataclasses import dataclass, asdict
from .news import news_minutes_factor


def _num(x, default=0.0):
    try: return float(x)
    except (TypeError, ValueError): return default


@dataclass(frozen=True)
class MinutesProjection:
    expected_minutes: float
    p_start: float
    p_60_plus: float
    p_appearance: float
    p_zero_minutes: float
    expected_minutes_if_start: float
    expected_minutes_if_bench: float
    confidence: float
    reasons: tuple[str, ...] = ()

    def as_dict(self):
        d = asdict(self)
        d["reasons"] = list(self.reasons)
        return d


def _base_minutes(player, history, prior_understat):
    recent = list(history or [])[-5:]
    reasons = []
    data_conf = 0.35
    if recent:
        weights = [0.10,0.12,0.18,0.25,0.35][-len(recent):]
        vals = [_num(r.get("minutes")) for r in recent]
        base = sum(a*b for a,b in zip(vals,weights)) / sum(weights)
        starts = sum(v >= 45 for v in vals) / len(vals)
        base = 0.72*base + 0.28*(90*starts)
        data_conf = 0.72 if len(recent) >= 4 else 0.58
        reasons.append(f"recent_minutes:{','.join(str(int(v)) for v in vals)}")
    else:
        pmins = _num((prior_understat or {}).get("time"))
        apps = _num((prior_understat or {}).get("games"))
        if apps > 0:
            base = min(88.0, pmins/apps)
            data_conf = 0.42
            reasons.append("prior_season_minutes")
        else:
            pos = int(player.get("element_type") or 0)
            base = {1:86,2:78,3:74,4:72}.get(pos,72)
            data_conf = 0.25
            reasons.append("position_prior")
    return base, data_conf, recent, reasons


def project_minutes(player, history, prior_understat, news_index, congestion_days=None) -> MinutesProjection:
    base, confidence, recent, reasons = _base_minutes(player, history, prior_understat)

    status = player.get("status")
    chance = player.get("chance_of_playing_next_round")
    availability = 1.0
    if status in {"i","s","u"}:
        availability = 0.10
        reasons.append(f"status:{status}")
    elif chance is not None:
        availability = max(0.0, min(1.0, _num(chance)/100))
        reasons.append(f"chance:{int(_num(chance))}")

    nf, news_conf = news_minutes_factor(player.get("web_name",""), news_index)
    availability *= max(0.0, min(1.05, nf))
    if news_conf == "HIGH":
        confidence = max(confidence, 0.80 if nf in {0.0,1.0,1.05} else 0.68)
        reasons.append("high_conf_news")
    elif news_conf == "MEDIUM":
        confidence = max(confidence, 0.62)
        reasons.append("medium_conf_news")

    recent_vals = [_num(r.get("minutes")) for r in recent]
    start_rate = sum(v >= 45 for v in recent_vals) / len(recent_vals) if recent_vals else min(0.95, base/90)
    cameo_rate = sum(0 < v < 45 for v in recent_vals) / len(recent_vals) if recent_vals else max(0.02, 0.22*(1-start_rate))
    p_start = max(0.0, min(0.99, (0.35*(base/90) + 0.65*start_rate) * availability))

    if congestion_days is not None and congestion_days < 4:
        # Congestion is modeled principally as rotation/start risk, not a blanket
        # percentage cut to every projected minute in every fixture.
        p_start *= 0.90
        reasons.append("short_turnaround")

    p_bench_appearance = min(max(0.0, 1-p_start), cameo_rate * availability)
    p_appearance = max(0.0, min(1.0, p_start + p_bench_appearance))
    start_minutes = max(55.0, min(90.0, 0.55*max(base,60.0) + 0.45*82.0))
    bench_minutes = 16.0
    expected = p_start*start_minutes + p_bench_appearance*bench_minutes
    p60_if_start = max(0.25, min(0.98, (start_minutes-45)/35))
    p60 = p_start*p60_if_start

    return MinutesProjection(
        expected_minutes=round(max(0.0,min(90.0,expected)),1),
        p_start=round(p_start,4),
        p_60_plus=round(p60,4),
        p_appearance=round(p_appearance,4),
        p_zero_minutes=round(1-p_appearance,4),
        expected_minutes_if_start=round(start_minutes,1),
        expected_minutes_if_bench=bench_minutes,
        confidence=round(max(0.0,min(1.0,confidence)),3),
        reasons=tuple(reasons),
    )


def expected_minutes(player, history, prior_understat, news_index, congestion_days=None):
    """V2-compatible adapter returning the historical (minutes, label) tuple."""
    p = project_minutes(player, history, prior_understat, news_index, congestion_days)
    label = "HIGH" if p.confidence >= .75 else ("MEDIUM" if p.confidence >= .5 else "LOW")
    return p.expected_minutes, label
