
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from time import monotonic
import json, os
from .fpl import FPLClient,next_event
from .state import load_public_state
from .stats import load_external_stats
from .rules import season_start_year
from .news import research_news,news_by_player
from .projections import build_projections
from .optimizer import initial_build_plans,managed_plans,plans_csv,plan_metrics
from .multigw import ManagerState, plan_multigw
from .captaincy import recommend_captaincy
from .elite import discover,summarize
from .chips import opportunity_map,augment_with_chip_plans,evaluate_wc_fh_shadow
from .decision import deterministic_decision, explanation_needed
from .explainer import build_explanation_packet, explain
from .validator import validate_plan
from .render import render_report
from .emailer import send_email
from .schedule import classify_window
from .confidence import recommendation_confidence
from .report_state import load as load_report_state,gw_state,mark_sent,mark_late_checked
from .runtime import RuntimeBudget, stage
from .decision_compare import compare_v2_v3
from .backtest.snapshots import write_snapshot

ROOT=Path(__file__).resolve().parents[2]
def load_cfg():return json.loads((ROOT/"config/manager.json").read_text())
def compact_plan(p, rank=None):
    out={k:v for k,v in p.items() if k!="metrics"}|{"metrics":{k:v for k,v in p["metrics"].items() if k!="lineups"}}
    if rank is not None: out["optimizer_rank"]=rank
    return out

def summaries_for_candidates(client,players,state,runtime_cfg=None):
    runtime_cfg=runtime_cfg or {}
    owned={int(x["player_id"]) for x in state.get("squad",[])}
    scored=[]
    for p in players:
        score=float(p.get("ep_next") or 0)*3+float(p.get("selected_by_percent") or 0)*.05+float(p.get("total_points") or 0)*.02+(1000 if int(p["id"]) in owned else 0)
        scored.append((score,int(p["id"])))
    cap=int(runtime_cfg.get("candidate_summary_players",45))
    ids=[pid for _,pid in sorted(scored,reverse=True)[:cap]]
    out={}
    timeout=float(runtime_cfg.get("bulk_fpl_timeout_seconds",6))
    retries=int(runtime_cfg.get("bulk_fpl_retries",1))
    budget=float(runtime_cfg.get("candidate_summary_budget_seconds",75))
    ex=ThreadPoolExecutor(max_workers=int(runtime_cfg.get("bulk_fpl_workers",10)))
    fut={ex.submit(lambda x: FPLClient(timeout=timeout,retries=retries).element_summary(x),pid):pid for pid in ids}
    pending=set(fut); deadline=monotonic()+budget
    try:
        while pending:
            remaining=deadline-monotonic()
            if remaining<=0:break
            try:f=next(as_completed(pending,timeout=remaining))
            except TimeoutError:break
            pending.remove(f)
            try:out[fut[f]]=f.result()
            except Exception:pass
        for f in pending:f.cancel()
    finally:
        ex.shutdown(wait=False,cancel_futures=True)
    if pending:
        print(f"::warning::Candidate summary budget exhausted after {budget:.0f}s; continuing with {len(out)}/{len(ids)} summaries.",flush=True)
    return out

def due_info(cfg,nxt):
    forced=os.getenv("FORCE_REPORT","").strip().lower()
    report=os.getenv("REPORT_TYPE","").strip().lower()
    delivery=os.getenv("DELIVERY_MODE","").strip().lower()
    if report:return report,delivery or "standard"
    kind,_,mode=classify_window(nxt["deadline_time"],tuple(cfg["preview_window_hours"]),tuple(cfg["final_window_hours"]),
        timezone_name=cfg["timezone"],sleep_cutoff_hour=cfg["sleep_cutoff_hour"],wake_hour=cfg["wake_hour"],sleep_safe_send_hour=cfg["sleep_safe_send_hour"])
    if forced in {"preview","final"}:return forced,"forced"
    return kind,mode

def late_check(cfg,gw,client,players_by_id):
    state=load_report_state(); g=gw_state(state,gw); fp=g.get("final_plan")
    if not fp:
        mark_late_checked(gw);return 0
    starters=fp.get("starter_names",[])
    old_claims={x.get("claim") for x in (g.get("final_news") or {}).get("items",[])}
    news,w=research_news(starters,cfg["news"]["allowed_domains"],os.getenv("OPENAI_MODEL","gpt-5"),"late_check",g.get("final_sent_at"))
    material=[x for x in news.get("items",[]) if x.get("confidence") in {"HIGH","MEDIUM"} and x.get("status") in {"ruled_out","major_doubt","rotation_risk"} and x.get("claim") not in old_claims]
    if material:
        body="# FPL Material Late News Alert\n\n## Action required\n"+ "\n".join(f"- **{x['player']}**: {x['claim']} ({x['confidence']}, {x['source_title']})" for x in material)
        body+="\n\nThis alert was sent only because material post-final news affected a player in the recommended XI. Re-open FPL before the deadline."
        send_email(f"FPL GW{gw} MATERIAL late-news alert",body,[(f"fpl-gw{gw}-late-news.json",json.dumps(news,indent=2),"application/json")])
    mark_late_checked(gw);return 0

def main():
    cfg=load_cfg(); runtime_cfg=cfg.get("runtime",{}); budget=RuntimeBudget(runtime_cfg.get("total_budget_seconds",1080))
    team_id=int(os.getenv("FPL_TEAM_ID",cfg["team_id"]));client=FPLClient()
    with stage("bootstrap_and_fixtures"):
        boot=client.bootstrap();fixtures=client.fixtures();nxt=next_event(boot["events"])
    if not nxt:return 0
    gw=int(nxt["id"]);kind,delivery=due_info(cfg,nxt)
    if not kind:return 0
    players=boot["elements"];players_by_id={int(p["id"]):p for p in players};teams={int(t["id"]):t["name"] for t in boot["teams"]}
    if kind=="late_check":return late_check(cfg,gw,client,players_by_id)

    with stage("public_state"):
        state=load_public_state(client,team_id,gw,players_by_id)
    if not state.get("actionable"):
        send_email(f"FPL GW{gw} recommendation withheld","# FPL Recommendation Withheld\n\n## Manual check required\n"+"\n".join(f"- {x}" for x in state.get("warnings",[])))
        return 2

    with stage("candidate_summaries"):
        summaries={} if gw == 1 else summaries_for_candidates(client,players,state,runtime_cfg)
    owned={int(x["player_id"]) for x in state.get("squad",[])}
    ranked=sorted(players,key=lambda p:(int(p["id"]) in owned,float(p.get("ep_next") or 0),float(p.get("selected_by_percent") or 0)),reverse=True)
    news_names=[p["web_name"] for p in ranked[:cfg["news"]["max_players"]]]
    rs=gw_state(load_report_state(),gw)
    fresh_after=rs.get("preview_sent_at") if kind=="final" else None
    with stage("news_research"):
        news,warn_news=research_news(
            news_names,cfg["news"]["allowed_domains"],os.getenv("OPENAI_MODEL","gpt-5"),kind,fresh_after,
            retry_attempts=int(cfg["news"].get("retry_attempts",2)),
            per_attempt_timeout_seconds=float(cfg["news"].get("per_attempt_timeout_seconds",25)),
        ) if cfg["news"]["enabled"] else ({"items":[],"freshness_note":"disabled","status":"DEGRADED"},[])
    nidx=news_by_player(news)

    with stage("external_stats"):
        external,warn_stats=load_external_stats({**cfg["stats"],"cache_dir":cfg["stats_cache_dir"]},season_start_year(cfg.get("season", "2026/27")))
    with stage("projections"):
        projections=build_projections(players,teams,fixtures,gw,summaries,external,nidx,cfg["projection_horizon_gws"],team_rows=boot.get("teams",[]),season=cfg.get("season","2026/27"))
    proj_by_id={r["player_id"]:r for r in projections}
    multigw_shadow=[]
    with stage("optimizer"):
        if state["mode"]=="gw1_initial_build":
            plans=initial_build_plans(players,players_by_id,proj_by_id,gw,cfg);base=None
        else:
            plans,base=managed_plans(state,players_by_id,projections,proj_by_id,gw,cfg)
    mg_cfg=cfg.get("multigw",{})
    if mg_cfg.get("enabled") or mg_cfg.get("shadow_mode"):
        try:
            with stage("multigw_shadow"):
                mg_state=ManagerState.from_public_state(state,gw)
                multigw_shadow=plan_multigw(
                    mg_state,players_by_id,projections,proj_by_id,
                    planning_horizon=int(mg_cfg.get("planning_horizon",4)),
                    candidate_per_position=int(mg_cfg.get("candidate_per_position",8)),
                    beam_width=int(mg_cfg.get("beam_width",60)),
                    max_transfers_per_gw=int(mg_cfg.get("max_transfers_per_gw",2)),
                    bench_weight=float(cfg.get("bench_weight",.2)),
                    discount=float(mg_cfg.get("discount",.97)),
                    top_n=6,
                    cache_enabled=bool(mg_cfg.get("cache_enabled",True)),
                    include_chips=False,
                    dominance_pruning=bool(mg_cfg.get("dominance_pruning",True)),
                    runtime_budget_seconds=float(mg_cfg.get("runtime_budget_seconds",25)),
                )
        except Exception as exc:
            state.setdefault("warnings",[]).append(f"V3 multi-GW shadow planner unavailable: {exc}")
    if not plans:
        send_email(f"FPL GW{gw} recommendation withheld","# FPL Recommendation Withheld\n\n- Optimizer produced no legal plan.");return 3

    captaincy_shadow={}
    cap_cfg=cfg.get("captaincy",{})
    if plans and cap_cfg.get("probabilistic_shadow",False):
        try:
            captaincy_shadow=recommend_captaincy(
                plans[0]["lineup"]["starters"],proj_by_id,gw,
                downside_penalty=float(cap_cfg.get("downside_penalty",.08)),
                upside_bonus=float(cap_cfg.get("upside_bonus",.03)),
                defender_override_margin=float(cap_cfg.get("probabilistic_defender_override_margin",1.25)),
            )
        except Exception as exc:
            state.setdefault("warnings",[]).append(f"V3 probabilistic captaincy shadow unavailable: {exc}")
    chip_map=opportunity_map(fixtures,teams,gw,cfg)
    plans=augment_with_chip_plans(plans,state,players,players_by_id,proj_by_id,gw,cfg,chip_map)
    v2_v3_comparison=compare_v2_v3(plans[0] if plans else None,multigw_shadow) if state["mode"] != "gw1_initial_build" else {"status":"not_applicable"}
    # WC/FH are intentionally shadow-only. Compare them with the best non-chip
    # sequential path under a bounded runtime, but never add them to production
    # optimizer_plans or allow the AI adjudicator to select them.
    wc_fh_shadow={"status":"not_run","production_policy":"shadow_only"}
    if state["mode"] != "gw1_initial_build" and cfg.get("chips",{}).get("wc_fh_shadow",{}).get("enabled",True):
        current_ids={int(x["player_id"]) for x in state.get("squad",[])}
        current_rows=[r for r in projections if r["player_id"] in current_ids]
        chip_all_low=bool(current_rows) and all(r.get("confidence")=="LOW" for r in current_rows)
        if budget.can_spend(70, reserve=180):
            try:
                with stage("wc_fh_shadow_comparison"):
                    wc_fh_shadow=evaluate_wc_fh_shadow(
                        state,players_by_id,projections,proj_by_id,gw,cfg,chip_map,
                        news_status=news.get("status","OK"),all_low=chip_all_low,
                    )
            except Exception as exc:
                wc_fh_shadow={"status":"unavailable","production_policy":"shadow_only","reason":str(exc)}
                state.setdefault("warnings",[]).append(f"WC/FH shadow comparison unavailable: {exc}")
        else:
            wc_fh_shadow={"status":"skipped_runtime_guard","production_policy":"shadow_only"}
    chip_map["wildcard_freehit_shadow"]=wc_fh_shadow
    public_gw=gw-1 if gw>1 else None
    if gw == 1:
        cache, warn_elite = {}, []
        elite = {
            "status": "unavailable",
            "reason": "GW1 has no locked elite-manager picks; cohort discovery is skipped to avoid useless API work.",
            "weight_current": 0.0
        }
    elif cfg["elite"]["enabled"]:
        with stage("elite_discovery"):
            cache,warn_elite=discover(client,cfg["elite"],gw,cfg["elite_cache_file"],runtime_cfg)
        with stage("elite_signal"):
            elite=summarize(client,cache,public_gw,players_by_id,gw,runtime_cfg)
    else:
        cache,warn_elite={},[]
        elite={"status":"disabled"}

    pe=sorted(projections,key=lambda r:(r["player_id"] in owned,r["gw6"],r["gw3"]),reverse=True)[:90]
    if state["mode"]=="gw1_initial_build":
        decision_audit={
            "production_engine":"V3 GW1 probabilistic/structural reranker",
            "shadow_engine":None,
            "captaincy_shadow_status":"available" if captaincy_shadow else "unavailable",
            "captaincy_shadow":captaincy_shadow,
            "agreement":"Legacy ILP is candidate generation only; final GW1 ranking is V3 probabilistic.",
            "wc_fh_policy":"HOLD in GW1; WC/FH shadow-only thereafter until sequential validation.",
            "decision_authority":"deterministic",
        }
    else:
        decision_audit={
            "production_engine":"V2 managed optimizer",
            "shadow_engine":"V3 multi-GW planner" if multigw_shadow else None,
            "captaincy_shadow_status":"available" if captaincy_shadow else "unavailable",
            "captaincy_shadow":captaincy_shadow,
            "agreement":(f"{v2_v3_comparison.get('label')}: production and V3 first actions " + ("agree." if v2_v3_comparison.get("same_first_action") else "differ; shadow remains advisory.")) if v2_v3_comparison.get("status")=="available" else "V3 comparison unavailable; production remains V2.",
            "v2_v3_comparison":v2_v3_comparison,
            "equivalence_band_points":float(cfg.get("optimizer",{}).get("near_tie_cluster_width_points",.75)),
            "wc_fh_policy":"Wildcard/Free Hit are shadow-only and cannot be selected by production.",
            "decision_authority":"deterministic",
        }

    # Production plan selection is now fully deterministic. cluster_sort() has
    # already resolved near-ties using robustness/flexibility; AI is optional
    # explanation only and cannot modify the selected plan.
    decision=deterministic_decision(plans,cfg,v2_v3=v2_v3_comparison,news=news,elite=elite)
    lookup={p["plan_id"]:p for p in plans}
    chosen=lookup[decision["plan_id"]]
    top=plans[0]

    sorted_scores=sorted((p["optimizer_score"] for p in plans),reverse=True)
    sep=(sorted_scores[0]-sorted_scores[1]) if len(sorted_scores)>1 else 9
    decision["confidence"]=recommendation_confidence(state,chosen,proj_by_id,warn_news,warn_stats+warn_elite,sep)
    eq_band=float(cfg.get("optimizer",{}).get("near_tie_cluster_width_points",.75))
    if sep <= eq_band:
        decision["plan_separation_note"]=f"Top plans are inside the {eq_band:.2f}-point equivalence band (numerical separation {sep:.2f}); treat the point gap as noise and prefer robustness/flexibility tie-breaks."
    else:
        decision["plan_separation_note"]=f"Optimizer separation between the top two plans: {sep:.2f} points."
    decision["news_status"]=news.get("status","OK")

    # Optional, low-cost explanation pass. It receives only the already-final
    # recommendation plus compact comparison facts. Failure never affects the
    # selected plan or delivery.
    ai_cfg=cfg.get("ai",{})
    decision["ai_explanation_used"]=False
    if ai_cfg.get("explanation_enabled",True) and explanation_needed(decision,v2_v3=v2_v3_comparison,news=news,chosen=chosen,cfg=cfg):
        if budget.can_spend(float(ai_cfg.get("explanation_timeout_seconds",25)),reserve=45):
            try:
                with stage("ai_explanation"):
                    alt_plan=lookup.get(decision.get("alternative_plan_id"))
                    exp_packet=build_explanation_packet(chosen,alt_plan,decision,v2_v3_comparison,players_by_id,news,wc_fh_shadow)
                    exp,_=explain(exp_packet,model=os.getenv("OPENAI_EXPLANATION_MODEL") or ai_cfg.get("explanation_model"),timeout=float(ai_cfg.get("explanation_timeout_seconds",25)))
                if exp:
                    decision["executive_reasoning"]=exp.get("executive_reasoning") or decision["executive_reasoning"]
                    if exp.get("v2_v3_note"):
                        decision["v2_v3_explanation"]=exp["v2_v3_note"]
                    if exp.get("risk_note"):
                        decision.setdefault("risks",[]).append(exp["risk_note"])
                    decision["ai_explanation_used"]=True
            except Exception as exc:
                state.setdefault("warnings",[]).append(f"Optional AI explanation unavailable: {exc}")
        else:
            state.setdefault("warnings",[]).append("Optional AI explanation skipped by runtime guard; deterministic report retained.")

    payload={"mode":state["mode"],"report_type":kind,"delivery_mode":delivery,"gameweek":gw,
      "objective":cfg["objective"],"risk_profile":cfg["risk_profile"],"state":state,
      "optimizer_plans":[compact_plan(p,i+1) for i,p in enumerate(plans)],"projection_evidence":pe,
      "multigw_shadow":multigw_shadow,"v2_v3_comparison":v2_v3_comparison,"captaincy_shadow":captaincy_shadow,"decision_audit":decision_audit,"elite_signal":elite,"chip_opportunities":chip_map,"news":news,
      "warnings":state.get("warnings",[])+warn_news+warn_stats+warn_elite,
      "policy":{"projection_weights":cfg["projection_weights"],
                "bench_valuation":"probabilistic auto-sub-aware" if state["mode"]=="gw1_initial_build" else f"legacy managed weight {cfg['bench_weight']}",
                "wildcard_freehit":"shadow_only; never selectable from optimizer_plans",
                "decision_authority":"deterministic","ai_role":"optional explanation only","alternative_margin":cfg["alternative_margin_points"]}}

    recompute_mode="probabilistic" if chosen.get("optimizer_engine")=="V3_GW1_PROBABILISTIC_RERANK" else "robust"
    recompute_bench=0.0 if recompute_mode=="probabilistic" else cfg["bench_weight"]
    recomputed=plan_metrics(chosen["squad_ids"],proj_by_id,gw,cfg["projection_weights"],recompute_bench,chip=chosen.get("chip"),selection_mode=recompute_mode)
    errors=validate_plan(chosen,players_by_id,proj_by_id,state,gw,recomputed)
    if errors:
        send_email(f"FPL GW{gw} recommendation withheld","# FPL Recommendation Withheld\n\n"+"\n".join(f"- {e}" for e in errors));return 6

    body=render_report(gw,kind,delivery,state["mode"],chosen,decision,players_by_id,proj_by_id,base,chip_map,elite,news,decision_audit=decision_audit)
    evidence={"generated_at":datetime.now(timezone.utc).isoformat(),"gameweek":gw,"state":state,"news":news,
      "sources":[{"url":x.get("source_url"),"title":x.get("source_title"),"timestamp":x.get("published_at"),"tier":x.get("source_tier"),"confidence":x.get("confidence"),"claim":x.get("claim")} for x in news.get("items",[])],
      "external_stats_provider":external.get("provider"),"projection_model":{"type":"component model","weights":cfg["projection_weights"],
      "bench_valuation":"probabilistic auto-sub-aware" if state["mode"]=="gw1_initial_build" else f"legacy managed weight {cfg['bench_weight']}"},
      "projections":projections,"multigw_shadow":multigw_shadow,"v2_v3_comparison":v2_v3_comparison,"captaincy_shadow":captaincy_shadow,"decision_audit":decision_audit,"decision":decision,"elite":elite,"chip_opportunities":chip_map,"selected_plan":compact_plan(chosen),"warnings":payload["warnings"]}
    try:
        snap_now=datetime.now(timezone.utc).isoformat()
        snapshot={
          "schema_version":1,"generated_at":snap_now,"deadline":nxt.get("deadline_time"),"gameweek":gw,"report_type":kind,
          "state":state,"players_by_id":players_by_id,"projections":projections,"config":cfg,
          "v2_plans":[compact_plan(p,i+1) for i,p in enumerate(plans)],"selected_plan":compact_plan(chosen),"decision":decision,"v3_paths":multigw_shadow,"v2_v3_comparison":v2_v3_comparison,
          "evidence":[{"kind":"news","published_at":x.get("published_at"),"source":x.get("source_url")} for x in news.get("items",[]) if x.get("published_at")]
                    + [{"kind":"official_fpl","observed_at":snap_now},{"kind":"external_stats","observed_at":snap_now}],
        }
        write_snapshot(ROOT/f".state/backtest/gw{gw}-{kind}.json",snapshot)
    except Exception as exc:
        state.setdefault("warnings",[]).append(f"Backtest snapshot not written: {exc}")

    attachments=[(f"fpl-gw{gw}-decision-audit.json",json.dumps({"decision":decision,"decision_audit":decision_audit,"v2_v3_comparison":v2_v3_comparison},indent=2,default=str),"application/json"),
      (f"fpl-gw{gw}-evidence-pack.json",json.dumps(evidence,indent=2,default=str),"application/json"),
      (f"fpl-gw{gw}-optimizer-plans.csv",plans_csv(plans,players_by_id),"text/csv")]
    subject=f"FPL GW{gw} {'Sleep-safe Final' if delivery=='sleep_safe' else kind.title()} Recommendation"
    send_email(subject,body,attachments)
    starter_names=[players_by_id[x]["web_name"] for x in chosen["lineup"]["starters"]]
    if delivery != "forced":
        mark_sent(gw,kind,delivery,{"plan_id":chosen["plan_id"],"starter_names":starter_names},news)
    return 0
if __name__=="__main__":raise SystemExit(main())
