
from __future__ import annotations

POS={1:"Goalkeepers",2:"Defenders",3:"Midfielders",4:"Forwards"}

def money(t): return f"£{t/10:.1f}m"

def player_name(pid,players): return players[int(pid)]["web_name"]

def render_report(gw,kind,delivery,mode,plan,decision,players,proj,base_plan=None,chip_map=None,elite=None,news=None):
    lines=[]
    title=f"FPL GW{gw} {'Initial Squad' if mode=='gw1_initial_build' else kind.title()} Recommendation"
    lines += [f"# {title}","", "## Executive action"]
    if delivery=="sleep_safe":
        lines += ["- **Sleep-safe final:** sent before the 23:00 Beijing cutoff; overnight team news after this report is not included."]
    lines += [f"- **Confidence:** {decision['confidence']}",f"- {decision['executive_reasoning']}"]
    if mode=="gw1_initial_build":
        lines += ["","## Initial squad"]
        for pos in (1,2,3,4):
            lines += ["",f"### {POS[pos]}"]
            for pid in [x for x in plan["squad_ids"] if proj[x]["position"]==pos]:
                lines.append(f"- {player_name(pid,players)} — {money(proj[pid]['price'])}")
        spent=sum(proj[x]["price"] for x in plan["squad_ids"])
        lines += ["","## Budget check",f"- Squad cost: **{money(spent)}**",f"- Bank: **{money(plan['bank_after'])}**"]
    else:
        lines += ["","## Transfers"]
        if plan.get("chip") in {"wildcard","freehit"}:
            lines.append(f"- **ACTIVATE {plan['chip'].upper()}** and use the optimized 15-player squad shown in optimizer-plans.csv/evidence pack.")
            lines.append(f"- Bank after rebuild: **{money(plan['bank_after'])}**")
        elif not plan["transfers"]:
            lines.append("- **ROLL** — make no transfer.")
        else:
            for t in plan["transfers"]:
                lines.append(f"- {player_name(t['out'],players)} → **{player_name(t['in'],players)}** ({money(t['sell'])} sold / {money(t['buy'])} bought)")
            lines.append(f"- Hit cost: **-{plan['hit_cost']}**" if plan["hit_cost"] else "- Hit cost: **0**")
            lines.append(f"- Bank after moves: **{money(plan['bank_after'])}**")
    lu=plan["lineup"]
    lines += ["","## Starting XI"]
    for pid in lu["starters"]:
        tag=" **(C)**" if pid==lu["captain"] else (" **(VC)**" if pid==lu["vice_captain"] else "")
        lines.append(f"- {player_name(pid,players)}{tag}")
    lines += ["","## Bench order"]
    for i,pid in enumerate(lu["bench"],1): lines.append(f"{i}. {player_name(pid,players)}")
    lines += ["","## Captaincy",f"- Captain: **{player_name(lu['captain'],players)}**",f"- Vice-captain: **{player_name(lu['vice_captain'],players)}**"]
    lines += ["","## Chip decision",f"- **{plan.get('chip', '').upper() if plan.get('chip') else 'HOLD all chips'}**",f"- {decision['chip_reasoning']}"]
    lines += ["","## Expected gain / projections"]
    if base_plan:
        gain=plan["metrics"]["weighted"]-base_plan["metrics"]["weighted"]-plan["hit_cost"]
        lines.append(f"- Weighted gain versus no-action: **{gain:+.2f}** projected points")
    lines += [f"- GW+1: **{plan['metrics']['gw1']:.2f}**",f"- Next 3 GWs: **{plan['metrics']['gw3']:.2f}**",f"- Next 6 GWs: **{plan['metrics']['gw6']:.2f}**"]
    lines += ["","## Elite-manager signal",f"- {decision['elite_signal']}"]
    lines += ["","## Key news and minutes risks"]
    for x in decision.get("news_summary") or ["No material fresh-news item changed the plan."]: lines.append(f"- {x}")
    for x in decision.get("risks",[]): lines.append(f"- Risk: {x}")
    lines += ["","## Alternative"]
    if decision.get("alternative_plan_id"):
        lines.append(f"- Alternative optimizer plan: `{decision['alternative_plan_id']}`. See optimizer-plans.csv for exact comparison.")
    else:
        lines.append("- No close alternative identified.")
    lines += ["","## Confidence / data quality",f"- Overall: **{decision['confidence']}**"]
    if decision.get("plan_separation_note"):
        lines.append(f"- {decision['plan_separation_note']}")
    if decision.get("news_status"):
        lines.append(f"- News research status: **{decision['news_status']}**")
    lines.append("- Exact legality, affordability, lineup, chip eligibility and projection arithmetic were recomputed after AI selection.")
    return "\n".join(lines)
