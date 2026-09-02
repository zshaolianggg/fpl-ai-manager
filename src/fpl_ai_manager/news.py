
from __future__ import annotations
from datetime import datetime, timezone
import json, os, time

NEWS_SCHEMA = {
  "type":"json_schema",
  "name":"fpl_news_research",
  "strict":True,
  "schema":{
    "type":"object",
    "additionalProperties":False,
    "properties":{
      "items":{
        "type":"array",
        "items":{
          "type":"object",
          "additionalProperties":False,
          "properties":{
            "player":{"type":"string"},
            "status":{"type":"string","enum":["ruled_out","major_doubt","minor_doubt","fit","likely_start","rotation_risk","role_change","no_material_update"]},
            "claim":{"type":"string"},
            "source_title":{"type":"string"},
            "source_url":{"type":"string"},
            "source_tier":{"type":"string","enum":["official","reputable","specialist"]},
            "confidence":{"type":"string","enum":["HIGH","MEDIUM","LOW"]},
            "published_at":{"type":["string","null"]}
          },
          "required":["player","status","claim","source_title","source_url","source_tier","confidence","published_at"]
        }
      },
      "freshness_note":{"type":"string"}
    },
    "required":["items","freshness_note"]
  }
}

SYSTEM = """Research only material FPL availability, expected-minutes, rotation, tactical-role and suspension news for the supplied players.
Source hierarchy is strict: official club/Premier League first; reputable football reporting second; specialist interpretation only if necessary.
Do not use social-media/X sources. Do not invent publication times. If sources conflict, reflect the uncertainty and lower confidence.
HIGH means official/confirmed. MEDIUM means reputable and corroborated. LOW means specialist interpretation or unresolved conflict.
Return only evidence that could change expected minutes, starting probability, role, or availability."""

def research_news(players, allowed_domains, model=None, report_type='preview', fresh_after=None, *, retry_attempts=2, per_attempt_timeout_seconds=25):
    if not os.getenv("OPENAI_API_KEY"):
        return {"items":[],"freshness_note":"OPENAI_API_KEY unavailable; news research skipped.","status":"DEGRADED","attempt_errors":["missing_api_key"]}, ["Fresh news unavailable: OPENAI_API_KEY missing."]
    from openai import OpenAI
    timeout=float(per_attempt_timeout_seconds)
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], max_retries=0, timeout=timeout)
    model = model or os.getenv("OPENAI_MODEL","gpt-5")
    prompt = (
        "Current UTC: " + datetime.now(timezone.utc).isoformat()
        + f"\nReport type: {report_type}."
        + (f"\nPrefer material updates published since {fresh_after}." if fresh_after else "")
        + "\nFor Final/Sleep-safe reports, prioritize same-day official press-conference/team updates."
        + "\nPlayers:\n" + "\n".join(f"- {x}" for x in players)
    )
    errors=[]
    attempts=[
        {"domains":allowed_domains,"label":"curated-domain search"},
        {"domains":allowed_domains[:12],"label":"reduced-domain search"},
        {"domains":None,"label":"fallback web search"},
    ][:max(1,min(3,int(retry_attempts)))]
    for i,attempt in enumerate(attempts,1):
        try:
            tool={"type":"web_search"}
            if attempt["domains"]:
                tool["filters"]={"allowed_domains":attempt["domains"]}
            resp=client.responses.create(
                model=model,instructions=SYSTEM,input=prompt+f"\nAttempt mode: {attempt['label']}",
                tools=[tool],text={"format":NEWS_SCHEMA},timeout=timeout
            )
            data=json.loads(resp.output_text)
            data["status"]="OK"
            data["attempt_errors"]=errors
            data["successful_attempt"]=attempt["label"]
            return data,[]
        except Exception as exc:
            errors.append(f"attempt {i} ({attempt['label']}): {type(exc).__name__}: {exc}")
            if i < len(attempts):
                time.sleep(1.5*i)
    note="Fresh news unavailable after retries. " + " | ".join(errors)
    return {"items":[],"freshness_note":note,"status":"DEGRADED","attempt_errors":errors}, [note]

def news_by_player(news):
    out = {}
    for item in news.get("items", []):
        out.setdefault(item["player"].lower(), []).append(item)
    return out

NEWS_MINUTES_RULES = {
    "ruled_out": 0.0,
    "major_doubt": 0.45,
    "minor_doubt": 0.80,
    "fit": 1.0,
    "likely_start": 1.05,
    "rotation_risk": 0.78,
    "role_change": 1.0,
    "no_material_update": 1.0,
}

def news_minutes_factor(player_name, indexed):
    items = indexed.get(player_name.lower(), [])
    factors = []
    for item in items:
        if item.get("confidence") in {"HIGH","MEDIUM"}:
            factors.append(NEWS_MINUTES_RULES.get(item.get("status"), 1.0))
    if not factors: return 1.0, "LOW" if items else None
    return min(factors), "HIGH" if any(i.get("confidence")=="HIGH" for i in items) else "MEDIUM"
