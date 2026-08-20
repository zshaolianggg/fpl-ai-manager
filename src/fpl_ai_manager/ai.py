
from __future__ import annotations
import json, os
from openai import OpenAI

DECISION_SCHEMA={
 "type":"json_schema","name":"fpl_plan_decision","strict":True,
 "schema":{"type":"object","additionalProperties":False,
   "properties":{
    "plan_id":{"type":"string"},
    "alternative_plan_id":{"type":["string","null"]},
    "confidence":{"type":"string","enum":["HIGH","MEDIUM","LOW"]},
    "executive_reasoning":{"type":"string"},
    "elite_signal":{"type":"string"},
    "chip_reasoning":{"type":"string"},
    "news_summary":{"type":"array","items":{"type":"string"}},
    "risks":{"type":"array","items":{"type":"string"}}
   },
   "required":["plan_id","alternative_plan_id","confidence","executive_reasoning","elite_signal","chip_reasoning","news_summary","risks"]
 }
}

SYSTEM="""You are the final strategic adjudicator for a Fantasy Premier League optimizer.
You MUST select plan_id from optimizer_plans. Never invent a player, transfer, price, bank figure, formation, chip, or plan.
The deterministic projection/optimizer is primary. Elite-manager behavior is only a bounded sanity/risk signal.
You may choose a non-#1 plan only if it is within 1.5 weighted projected points of #1, unless a material HIGH/MEDIUM news fact makes #1 unsafe; state that reason.
Use maximum overall rank with balanced risk. Hits are exceptional. Confirmed blanks/doubles matter for chips; unconfirmed rearrangements must not drive chip use.
Return one definitive plan. Return an alternative only when within 2 projected points or representing a materially different balanced-risk route.
Treat source hierarchy as official > reputable > specialist. Missing news lowers confidence but is not negative evidence."""

def decide(payload,model=None):
    client=OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    model=model or os.getenv("OPENAI_MODEL","gpt-5")
    resp=client.responses.create(model=model,instructions=SYSTEM,
                                 input=json.dumps(payload,separators=(",",":"),default=str),
                                 text={"format":DECISION_SCHEMA})
    return json.loads(resp.output_text), resp

def audit_text(payload,model=None):
    return ("FPL AI Manager v2 - final OpenAI adjudication request\n"
            "===================================================\n\n"
            f"model: {model or os.getenv('OPENAI_MODEL','gpt-5')}\n\n"
            "--- instructions ---\n"+SYSTEM+"\n\n--- input ---\n"+
            json.dumps(payload,indent=2,default=str))
