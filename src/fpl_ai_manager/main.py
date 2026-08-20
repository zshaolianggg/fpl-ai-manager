
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import json, os
from .fpl import FPLClient,next_event
from .state import load_public_state
from .stats import load_external_stats
from .news import research_news,news_by_player
from .projections import build_projections
from .optimizer import initial_build_plans,managed_plans,plans_csv,plan_metrics
from .elite import discover,summarize
from .chips import opportunity_map,augment_with_chip_plans
from .ai import decide,audit_text
from .validator import validate_plan
from .render import render_report
from .emailer import send_email
from .schedule import classify_window
from .confidence import recommendation_confidence
from .report_state import load as load_report_state,gw_state,mark_sent,mark_late_checked

ROOT=Path(__file__).resolve().parents[2]
def load_cfg():return json.loads((ROOT/"config/manager.json").read_text())
def compact_plan(p):return {k:v for k,v in p.items() if k!="metrics"}|{"metrics":{k:v for k,v in p["metrics"].items() if k!="lineups"}}

def summaries_for_candidates(client,players,state):
    owned={int(x["player_id"]) for x in state.get("squad",[])}
    scored=[]
    for p in players:
        score=float(p.get("ep_next") or 0)*3+float(p.get("selected_by_percent") or 0)*.05+float(p.get("total_points") or 0)*.02+(1000 if int(p["id"]) in owned else 0)
        scored.append((score,int(p["id"])))
    ids=[pid for _,pid in sorted(scored,reverse=True)[:110]]
    out={}
    with ThreadPoolExecutor(max_workers=12) as ex:
        fut={ex.submit(lambda x: FPLClient().element_summary(x),pid):pid for pid in ids}
        for f in as_completed(fut):
            try:out[fut[f]]=f.result()
            except Exception:pass
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
    cfg=load_cfg();team_id=int(os.getenv("FPL_TEAM_ID",cfg["team_id"]));client=FPLClient()
    boot=client.bootstrap();fixtures=client.fixtures();nxt=next_event(boot["events"])
    if not nxt:return 0
    gw=int(nxt["id"]);kind,delivery=due_info(cfg,nxt)
    if not kind:return 0
    players=boot["elements"];players_by_id={int(p["id"]):p for p in players};teams={int(t["id"]):t["name"] for t in boot["teams"]}
    if kind=="late_check":return late_check(cfg,gw,client,players_by_id)

    state=load_public_state(client,team_id,gw,players_by_id)
    if not state.get("actionable"):
        send_email(f"FPL GW{gw} recommendation withheld","# FPL Recommendation Withheld\n\n## Manual check required\n"+"\n".join(f"- {x}" for x in state.get("warnings",[])))
        return 2

    summaries=summaries_for_candidates(client,players,state)
    owned={int(x["player_id"]) for x in state.get("squad",[])}
    ranked=sorted(players,key=lambda p:(int(p["id"]) in owned,float(p.get("ep_next") or 0),float(p.get("selected_by_percent") or 0)),reverse=True)
    news_names=[p["web_name"] for p in ranked[:cfg["news"]["max_players"]]]
    rs=gw_state(load_report_state(),gw)
    fresh_after=rs.get("preview_sent_at") if kind=="final" else None
    news,warn_news=research_news(news_names,cfg["news"]["allowed_domains"],os.getenv("OPENAI_MODEL","gpt-5"),kind,fresh_after) if cfg["news"]["enabled"] else ({"items":[],"freshness_note":"disabled"},[])
    nidx=news_by_player(news)

    external,warn_stats=load_external_stats({**cfg["stats"],"cache_dir":cfg["stats_cache_dir"]},2026)
    projections=build_projections(players,teams,fixtures,gw,summaries,external,nidx,cfg["projection_horizon_gws"])
    proj_by_id={r["player_id"]:r for r in projections}
    if state["mode"]=="gw1_initial_build":
        plans=initial_build_plans(players,players_by_id,proj_by_id,gw,cfg);base=None
    else:
        plans,base=managed_plans(state,players_by_id,projections,proj_by_id,gw,cfg)
    if not plans:
        send_email(f"FPL GW{gw} recommendation withheld","# FPL Recommendation Withheld\n\n- Optimizer produced no legal plan.");return 3

    chip_map=opportunity_map(fixtures,teams,gw,cfg)
    plans=augment_with_chip_plans(plans,state,players,players_by_id,proj_by_id,gw,cfg,chip_map)
    public_gw=gw-1 if gw>1 else None
    cache,warn_elite=discover(client,cfg["elite"],gw,cfg["elite_cache_file"]) if cfg["elite"]["enabled"] else ({},[])
    elite=summarize(client,cache,public_gw,players_by_id,gw) if cfg["elite"]["enabled"] else {"status":"disabled"}

    pe=sorted(projections,key=lambda r:(r["player_id"] in owned,r["gw6"],r["gw3"]),reverse=True)[:90]
    payload={"mode":state["mode"],"report_type":kind,"delivery_mode":delivery,"gameweek":gw,
      "objective":cfg["objective"],"risk_profile":cfg["risk_profile"],"state":state,
      "optimizer_plans":[compact_plan(p) for p in plans],"projection_evidence":pe,
      "elite_signal":elite,"chip_opportunities":chip_map,"news":news,
      "warnings":state.get("warnings",[])+warn_news+warn_stats+warn_elite,
      "policy":{"projection_weights":cfg["projection_weights"],"bench_weight":cfg["bench_weight"],
                "ai_override_margin":cfg["ai_override_margin_points"],"alternative_margin":cfg["alternative_margin_points"]}}
    decision,_=decide(payload,os.getenv("OPENAI_MODEL","gpt-5"))
    lookup={p["plan_id"]:p for p in plans}
    if decision["plan_id"] not in lookup:
        send_email(f"FPL GW{gw} recommendation withheld","# FPL Recommendation Withheld\n\n- AI selected an unknown optimizer plan.");return 4
    chosen=lookup[decision["plan_id"]];top=plans[0]
    gap=top["optimizer_score"]-chosen["optimizer_score"]
    material_news=any(i.get("confidence") in {"HIGH","MEDIUM"} and i.get("status") in {"ruled_out","major_doubt","rotation_risk"} for i in news.get("items",[]))
    if gap>cfg["ai_override_margin_points"] and not material_news:
        send_email(f"FPL GW{gw} recommendation withheld",f"# FPL Recommendation Withheld\n\n- AI override exceeded {cfg['ai_override_margin_points']} points without material news.");return 5

    recomputed=plan_metrics(chosen["squad_ids"],proj_by_id,gw,cfg["projection_weights"],cfg["bench_weight"],chip=chosen.get("chip"))
    errors=validate_plan(chosen,players_by_id,proj_by_id,state,gw,recomputed)
    if errors:
        send_email(f"FPL GW{gw} recommendation withheld","# FPL Recommendation Withheld\n\n"+"\n".join(f"- {e}" for e in errors));return 6

    alt=decision.get("alternative_plan_id")
    if alt not in lookup:decision["alternative_plan_id"]=None
    elif abs(chosen["optimizer_score"]-lookup[alt]["optimizer_score"])>cfg["alternative_margin_points"]:decision["alternative_plan_id"]=None

    sorted_scores=sorted((p["optimizer_score"] for p in plans),reverse=True)
    sep=(sorted_scores[0]-sorted_scores[1]) if len(sorted_scores)>1 else 9
    decision["confidence"]=recommendation_confidence(state,chosen,proj_by_id,warn_news,warn_stats+warn_elite,sep)
    body=render_report(gw,kind,delivery,state["mode"],chosen,decision,players_by_id,proj_by_id,base,chip_map,elite,news)
    evidence={"generated_at":datetime.now(timezone.utc).isoformat(),"gameweek":gw,"state":state,"news":news,
      "sources":[{"url":x.get("source_url"),"title":x.get("source_title"),"timestamp":x.get("published_at"),"tier":x.get("source_tier"),"confidence":x.get("confidence"),"claim":x.get("claim")} for x in news.get("items",[])],
      "external_stats_provider":external.get("provider"),"projection_model":{"type":"component model","weights":cfg["projection_weights"],"bench_weight":cfg["bench_weight"]},
      "projections":projections,"elite":elite,"chip_opportunities":chip_map,"selected_plan":compact_plan(chosen),"warnings":payload["warnings"]}
    attachments=[(f"fpl-gw{gw}-openai-prompt.txt",audit_text(payload),"text/plain"),
      (f"fpl-gw{gw}-evidence-pack.json",json.dumps(evidence,indent=2,default=str),"application/json"),
      (f"fpl-gw{gw}-optimizer-plans.csv",plans_csv(plans,players_by_id),"text/csv")]
    subject=f"FPL GW{gw} {'Sleep-safe Final' if delivery=='sleep_safe' else kind.title()} Recommendation"
    send_email(subject,body,attachments)
    starter_names=[players_by_id[x]["web_name"] for x in chosen["lineup"]["starters"]]
    if delivery != "forced":
        mark_sent(gw,kind,delivery,{"plan_id":chosen["plan_id"],"starter_names":starter_names},news)
    return 0
if __name__=="__main__":raise SystemExit(main())
