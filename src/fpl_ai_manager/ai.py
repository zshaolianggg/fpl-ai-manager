
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
The deterministic projection/optimizer is primary. Treat LOW-confidence projection gaps as uncertain rather than precise; do not rationalize extreme captaincy or chip use from tiny/noisy edges. Elite-manager behavior is only a bounded sanity/risk signal.
You may choose a non-#1 plan only if it is within 1.5 weighted projected points of #1, unless a material HIGH/MEDIUM news fact makes #1 unsafe; state that reason.
Use maximum overall rank with balanced risk. In GW1, HOLD all chips. Hits are exceptional. Confirmed blanks/doubles matter for chips; unconfirmed rearrangements must not drive chip use.
If all relevant projections are LOW confidence and there is no material HIGH/MEDIUM news, prefer optimizer rank #1 unless another plan has a clearly safer balanced-risk structure; never call a non-#1 plan the optimizer top plan. Return one definitive plan. Return an alternative only when within 2 projected points or representing a materially different balanced-risk route.
Treat source hierarchy as official > reputable > specialist. Missing news lowers confidence but is not negative evidence.
Never describe a shadow model as the model that selected the production plan. If optimizer_engine or decision_audit is supplied, name the production engine accurately. Do not mention a fixed 20% bench weighting for a V3 GW1 plan; V3 GW1 uses probabilistic auto-sub-aware bench valuation. If the selected squad has structural_diagnostics, explicitly flag unusual expensive deep-bench capital rather than rationalizing it."""

def decide(payload,model=None,timeout=90.0):
    client=OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    model=model or os.getenv("OPENAI_MODEL","gpt-5")
    resp=client.responses.create(model=model,instructions=SYSTEM,
                                 input=json.dumps(payload,separators=(",",":"),default=str),
                                 text={"format":DECISION_SCHEMA}, timeout=float(timeout))
    return json.loads(resp.output_text), resp

def audit_text(payload,model=None):
    return ("FPL AI Manager v3 - final OpenAI adjudication request\n"
            "===================================================\n\n"
            f"model: {model or os.getenv('OPENAI_MODEL','gpt-5')}\n\n"
            "--- instructions ---\n"+SYSTEM+"\n\n--- input ---\n"+
            json.dumps(payload,indent=2,default=str))
