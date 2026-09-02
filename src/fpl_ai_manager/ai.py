from __future__ import annotations
import json, os
try:
    from openai import OpenAI
except ImportError:  # lightweight/test environments
    OpenAI = None

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
Wildcard and Free Hit are SHADOW-ONLY in this build: never recommend activating either one, never describe either as the selected production chip, and never treat a positive shadow comparison as authority. They may be mentioned only as advisory monitoring evidence. Bench Boost and Triple Captain may still appear in production optimizer_plans when legal.
If plans are inside the configured near-tie/equivalence band, do NOT treat tiny score differences as meaningful precision. Prefer the plan with the stronger robustness/flexibility tie-break (secure minutes, no hit, useful bank/future routes) and explain that the point estimates are effectively tied. If all relevant projections are LOW confidence and there is no material HIGH/MEDIUM news, remain conservative; never call a non-#1 plan the numerical optimizer top plan. Return one definitive plan. Return an alternative only when within 2 projected points or representing a materially different balanced-risk route.
Treat source hierarchy as official > reputable > specialist. Missing news lowers confidence but is not negative evidence.
Never describe a shadow model as the model that selected the production plan. If optimizer_engine or decision_audit is supplied, name the production engine accurately. Do not mention a fixed 20% bench weighting for a V3 GW1 plan; V3 GW1 uses probabilistic auto-sub-aware bench valuation. If the selected squad has structural_diagnostics, explicitly flag unusual expensive deep-bench capital rather than rationalizing it."""


def _plan_compact(plan):
    metrics=plan.get("metrics") or {}
    lineup=plan.get("lineup") or {}
    return {
        "plan_id":plan.get("plan_id"),
        "optimizer_rank":plan.get("optimizer_rank"),
        "chip":plan.get("chip"),
        "transfers":plan.get("transfers",[]),
        "hit_cost":plan.get("hit_cost",0),
        "bank_after":plan.get("bank_after"),
        "optimizer_score":plan.get("optimizer_score"),
        "equivalence_tiebreak":plan.get("equivalence_tiebreak"),
        "within_equivalence_band":plan.get("within_equivalence_band"),
        "reason_flags":plan.get("reason_flags",[])[:5],
        "metrics":{k:metrics.get(k) for k in ("gw1","gw3","gw6","weighted") if k in metrics},
        "lineup":{
            "starters":lineup.get("starters",[]),
            "bench":lineup.get("bench",[]),
            "captain":lineup.get("captain"),
            "vice":lineup.get("vice"),
            "score":lineup.get("score"),
            "robust_score":lineup.get("robust_score"),
            "probabilistic_score":lineup.get("probabilistic_score"),
        },
        "structural_diagnostics":plan.get("structural_diagnostics"),
        "optimizer_engine":plan.get("optimizer_engine"),
    }


def _projection_compact(row):
    per=[]
    for gw,data in sorted((row.get("per_gw") or {}).items(), key=lambda x:int(x[0]))[:6]:
        if isinstance(data,dict):
            per.append({"gw":int(gw),"mean":data.get("mean_points",data.get("points")),"p_start":data.get("p_start"),"p_zero":data.get("p_zero_minutes"),"minutes":data.get("expected_minutes")})
        else:
            per.append({"gw":int(gw),"mean":data})
    return {
        "player_id":row.get("player_id"),"name":row.get("name"),"position":row.get("position"),"team":row.get("team"),"price":row.get("price"),
        "expected_minutes":row.get("expected_minutes"),"confidence":row.get("confidence"),"gw1":row.get("gw1"),"gw3":row.get("gw3"),"gw6":row.get("gw6"),"per_gw":per,
    }


def _path_compact(path):
    if not isinstance(path,dict): return path
    return {
        "score":path.get("score"),"first_action":path.get("first_action"),
        "steps":[{k:s.get(k) for k in ("gw","transfers","roll","chip","hit_cost","bank_after","free_transfers_after","lineup_score")} for s in (path.get("steps") or [])[:4]],
        "planner_diagnostics":path.get("planner_diagnostics"),
    }


def compact_payload(payload, *, max_plans=8, max_projections=40, max_news=16, max_paths=3):
    """Return the bounded evidence packet actually sent to the adjudicator.

    Full projections/evidence remain in attachments/backtest snapshots. The LLM
    only needs the shortlisted alternatives and the evidence relevant to them.
    """
    plans=list(payload.get("optimizer_plans") or [])[:max_plans]
    relevant=set()
    for p in plans:
        relevant.update(p.get("squad_ids") or [])
        lu=p.get("lineup") or {}
        relevant.update(lu.get("starters") or []); relevant.update(lu.get("bench") or [])
        for t in p.get("transfers") or []:
            if t.get("out") is not None: relevant.add(int(t["out"]))
            if t.get("in") is not None: relevant.add(int(t["in"]))
    projections=list(payload.get("projection_evidence") or [])
    focused=[r for r in projections if r.get("player_id") in relevant]
    seen={r.get("player_id") for r in focused}
    focused += [r for r in projections if r.get("player_id") not in seen][:max(0,max_projections-len(focused))]
    news=payload.get("news") or {}
    news_items=sorted(news.get("items") or [],key=lambda x:(x.get("confidence") in {"HIGH","MEDIUM"},x.get("status")!="no_material_update"),reverse=True)[:max_news]
    state=payload.get("state") or {}
    elite=payload.get("elite_signal") or {}
    chip=payload.get("chip_opportunities") or {}
    out={
        "mode":payload.get("mode"),"report_type":payload.get("report_type"),"delivery_mode":payload.get("delivery_mode"),"gameweek":payload.get("gameweek"),
        "objective":payload.get("objective"),"risk_profile":payload.get("risk_profile"),
        "state":{"mode":state.get("mode"),"bank":state.get("bank"),"free_transfers":state.get("free_transfers"),"chips_available":state.get("chips_available"),"warnings":(state.get("warnings") or [])[:8]},
        "optimizer_plans":[_plan_compact(p) for p in plans],
        "projection_evidence":[_projection_compact(r) for r in focused[:max_projections]],
        "multigw_shadow":[_path_compact(p) for p in (payload.get("multigw_shadow") or [])[:max_paths]],
        "v2_v3_comparison":payload.get("v2_v3_comparison"),
        "captaincy_shadow":payload.get("captaincy_shadow"),
        "decision_audit":payload.get("decision_audit"),
        "elite_signal":{k:elite.get(k) for k in ("status","weight_current","top_owned","top_captained","notes") if k in elite},
        "chip_opportunities":{"thresholds":chip.get("thresholds"),"modeled_opportunity_costs":chip.get("modeled_opportunity_costs"),"wildcard_freehit_shadow":chip.get("wildcard_freehit_shadow"),"wc_fh_policy":chip.get("wc_fh_policy")},
        "news":{"status":news.get("status"),"freshness_note":news.get("freshness_note"),"items":news_items},
        "warnings":(payload.get("warnings") or [])[:12],"policy":payload.get("policy"),
    }
    return out


def _fallback(payload, reason):
    plans=payload.get("optimizer_plans") or []
    if not plans:
        raise RuntimeError(f"OpenAI adjudication unavailable and no deterministic plan exists: {reason}")
    first=plans[0]
    alt=plans[1].get("plan_id") if len(plans)>1 else None
    return {
        "plan_id":first["plan_id"],"alternative_plan_id":alt,"confidence":"LOW",
        "executive_reasoning":f"AI adjudication unavailable ({reason}); deterministic optimizer rank #1 selected.",
        "elite_signal":"Elite evidence remains secondary; no AI override was applied.",
        "chip_reasoning":"Deterministic production chip policy retained.",
        "news_summary":[],"risks":["Final AI tie-break was skipped; review close plans manually if the optimizer separation is small."],
    }


def decide(payload,model=None,timeout=60.0):
    model=model or os.getenv("OPENAI_MODEL","gpt-5")
    compact=compact_payload(payload)
    compact_chars=len(json.dumps(compact,separators=(",",":"),default=str))
    print(f"::notice::OpenAI adjudication compact input chars={compact_chars}",flush=True)
    try:
        if OpenAI is None:
            raise RuntimeError("openai package unavailable")
        client=OpenAI(api_key=os.environ["OPENAI_API_KEY"],max_retries=0,timeout=float(timeout))
        resp=client.responses.create(model=model,instructions=SYSTEM,
                                     input=json.dumps(compact,separators=(",",":"),default=str),
                                     text={"format":DECISION_SCHEMA}, timeout=float(timeout))
        return json.loads(resp.output_text), resp
    except Exception as exc:
        reason=f"{type(exc).__name__}: {str(exc)[:240]}"
        print(f"::warning::OpenAI adjudication failed; using deterministic fallback. {reason}",flush=True)
        return _fallback(compact,reason), None


def audit_text(payload,model=None):
    compact=compact_payload(payload)
    raw=json.dumps(compact,indent=2,default=str)
    return ("FPL AI Manager v3 - final OpenAI adjudication request\n"
            "===================================================\n\n"
            f"model: {model or os.getenv('OPENAI_MODEL','gpt-5')}\n"
            f"compact_input_chars: {len(json.dumps(compact,separators=(',',':'),default=str))}\n\n"
            "--- instructions ---\n"+SYSTEM+"\n\n--- compact input actually sent ---\n"+raw)
