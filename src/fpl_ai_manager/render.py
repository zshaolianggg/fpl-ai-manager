
from __future__ import annotations

POS={1:"Goalkeepers",2:"Defenders",3:"Midfielders",4:"Forwards"}

def money(t): return f"£{t/10:.1f}m"

def player_name(pid,players): return players[int(pid)]["web_name"]

def render_report(gw,kind,delivery,mode,plan,decision,players,proj,base_plan=None,chip_map=None,elite=None,news=None,decision_audit=None):
    lines=[]
    title=f"FPL GW{gw} {'Initial Squad' if mode=='gw1_initial_build' else kind.title()} Recommendation"
    lines += [f"# {title}","", "## Executive action"]
    if delivery=="sleep_safe":
        lines += ["- **Sleep-safe final:** sent before the 23:00 Beijing cutoff; overnight team news after this report is not included."]
    lines += [f"- **Confidence:** {decision['confidence']}",f"- {decision['executive_reasoning']}"]
    if decision_audit:
        lines += ["", "## Decision engine audit"]
        lines.append(f"- Production optimizer: **{decision_audit.get('production_engine','unknown')}**")
        if decision_audit.get('decision_authority'):
            lines.append(f"- Decision authority: **{decision_audit['decision_authority'].upper()}** (AI cannot change the plan).")
        if decision_audit.get("shadow_engine"):
            lines.append(f"- Shadow optimizer: **{decision_audit['shadow_engine']}**")
        if decision_audit.get("captaincy_shadow_status"):
            lines.append(f"- Probabilistic captaincy shadow: **{decision_audit['captaincy_shadow_status']}**")
            cs=decision_audit.get('captaincy_shadow') or {}
            cands=cs.get('candidates') or []
            if cs.get('captain') is not None:
                cap=next((x for x in cands if int(x.get('player_id',-1))==int(cs['captain'])),{})
                vice=next((x for x in cands if int(x.get('player_id',-1))==int(cs.get('vice_captain',-1))),{})
                lines.append(f"- V3 captaincy shadow: **{player_name(cs['captain'],players)} (C)** / **{player_name(cs['vice_captain'],players)} (VC)**; captain utility {float(cap.get('utility',0)):.2f}, P(0 min) {float(cap.get('p_zero',0))*100:.1f}%.")
                if len(cands)>1:
                    altc=next((x for x in cands if int(x.get('player_id',-1))!=int(cs['captain'])),None)
                    if altc:
                        lines.append(f"- Next captain candidate: **{player_name(altc['player_id'],players)}**, utility {float(altc.get('utility',0)):.2f}.")
        if decision_audit.get("agreement"):
            lines.append(f"- V2/V3 agreement: {decision_audit['agreement']}")
        if decision_audit.get("wc_fh_policy"):
            lines.append(f"- WC/FH authority: **{decision_audit['wc_fh_policy']}**")
        comp=decision_audit.get("v2_v3_comparison") or {}
        if comp.get("status")=="available":
            v2_action="ROLL" if comp.get("v2_roll") else f"{len(comp.get('v2_transfers',[]))} transfer(s)"
            v3_action="ROLL" if comp.get("v3_roll") else f"{len(comp.get('v3_transfers',[]))} transfer(s)"
            lines.append(f"- V2 first action: **{v2_action}**; V3 shadow first action: **{v3_action}**; comparison: **{comp.get('label')}**.")
            if comp.get('v2_transfers'):
                named='; '.join(f"{player_name(t['out'],players)} → {player_name(t['in'],players)}" for t in comp['v2_transfers'])
                lines.append(f"- V2 route: **{named}**")
            elif comp.get('v2_roll'):
                lines.append("- V2 route: **ROLL**")
            if comp.get('v3_transfers'):
                named='; '.join(f"{player_name(t['out'],players)} → {player_name(t['in'],players)}" for t in comp['v3_transfers'])
                lines.append(f"- V3 shadow route: **{named}**")
            elif comp.get('v3_roll'):
                lines.append("- V3 shadow route: **ROLL**")
            future=(comp.get('v3_future_steps') or [])[1:3]
            for step in future:
                if step.get('transfers'):
                    named='; '.join(f"{player_name(t['out'],players)} → {player_name(t['in'],players)}" for t in step['transfers'])
                    lines.append(f"- V3 shadow GW{step.get('gw')} continuation: **{named}**")
                elif step.get('roll'):
                    lines.append(f"- V3 shadow GW{step.get('gw')} continuation: **ROLL**")
            if decision.get('v2_v3_explanation'):
                lines.append(f"- Why they differ: {decision['v2_v3_explanation']}")
        if decision_audit.get("equivalence_band_points") is not None:
            lines.append(f"- Near-tie policy: plans within **{float(decision_audit['equivalence_band_points']):.2f} pts** are treated as equivalent and resolved by robustness/flexibility rather than decimal score precision.")
    if mode=="gw1_initial_build":
        lines += ["","## Initial squad"]
        for pos in (1,2,3,4):
            lines += ["",f"### {POS[pos]}"]
            for pid in [x for x in plan["squad_ids"] if proj[x]["position"]==pos]:
                lines.append(f"- {player_name(pid,players)} — {money(proj[pid]['price'])}")
        spent=sum(proj[x]["price"] for x in plan["squad_ids"])
        lines += ["","## Budget check",f"- Squad cost: **{money(spent)}**",f"- Bank: **{money(plan['bank_after'])}**"]
        diag=plan.get("structural_diagnostics") or {}
        if diag:
            lines += ["", "## Squad structure diagnostics"]
            lines.append(f"- Starting-XI capital: **{money(diag.get('starting_cost_tenths',0))}**")
            lines.append(f"- Bench capital: **{money(diag.get('bench_cost_tenths',0))}**")
            lines.append(f"- Expected auto-sub contribution: **{diag.get('expected_auto_sub_points',0):.2f} pts**")
            deep=diag.get("expensive_deep_bench") or []
            if deep:
                starts=diag.get("expensive_deep_bench_future_starts_next5",{})
                details=", ".join(f"{player_name(pid,players)} ({int(starts.get(pid,0))}/5 projected future starts)" for pid in deep)
                lines.append(f"- Structural flag: expensive deep-bench capital in **{details}**; V3 only tolerates it when projected near-term starting usage offsets the opportunity cost.")
            else:
                lines.append("- Structural check: no expensive outfield player is parked in a deep bench slot.")
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
    signals=decision.get("transfer_signals") or []
    if signals and mode!="gw1_initial_build":
        lines += ["", "## Transfer signal strength"]
        seen=set()
        for sig in signals:
            key=(sig.get('out'),sig.get('in'))
            if key in seen: continue
            seen.add(key)
            lines.append(
                f"- {player_name(sig['out'],players)} → {player_name(sig['in'],players)}: **{sig.get('pair_strength','WEAK')}** replacement signal "
                f"({sig.get('pair_frequency',0)*100:.0f}% of sampled top plans); selling {player_name(sig['out'],players)} is **{sig.get('sell_strength','WEAK')}** "
                f"({sig.get('sell_frequency',0)*100:.0f}%)."
            )
            if len(seen)>=5: break
    lu=plan["lineup"]
    lines += ["","## Starting XI"]
    for pid in lu["starters"]:
        tag=" **(C)**" if pid==lu["captain"] else (" **(VC)**" if pid==lu["vice_captain"] else "")
        lines.append(f"- {player_name(pid,players)}{tag}")
    lines += ["","## Bench order"]
    for i,pid in enumerate(lu["bench"],1): lines.append(f"{i}. {player_name(pid,players)}")
    lines += ["","## Captaincy",f"- Captain: **{player_name(lu['captain'],players)}**",f"- Vice-captain: **{player_name(lu['vice_captain'],players)}**"]
    lines += ["","## Chip decision",f"- **{plan.get('chip', '').upper() if plan.get('chip') else 'HOLD all chips'}**",f"- {decision['chip_reasoning']}"]
    shadow=(chip_map or {}).get("wildcard_freehit_shadow") or {}
    if shadow and shadow.get("status") not in {"disabled","not_run"}:
        lines += ["", "## Wildcard / Free Hit shadow comparison"]
        lines.append("- **Advisory only:** Wildcard and Free Hit cannot be activated by the production optimizer in this build.")
        if shadow.get("baseline_non_chip_score") is not None:
            lines.append(f"- Best non-chip sequential path score: **{shadow['baseline_non_chip_score']:.2f}** over the shadow horizon.")
        for chip,label in (("wildcard","Wildcard"),("freehit","Free Hit")):
            item=(shadow.get("chips") or {}).get(chip) or {}
            if not item.get("available"):
                lines.append(f"- {label}: unavailable.")
            elif not item.get("evaluated"):
                lines.append(f"- {label}: shadow evaluation unavailable ({item.get('reason','runtime/search limit')}).")
            else:
                gate="PASS" if item.get("confidence_gate_passed") else "FAIL"
                lines.append(
                    f"- {label}: gross edge vs best non-chip **{item.get('gross_advantage_vs_best_non_chip',0):+.2f}**, "
                    f"preservation reserve **{item.get('preservation_reserve',0):.2f}**, "
                    f"net edge **{item.get('net_opportunity_edge',0):+.2f}**; confidence/news gate **{gate}**. Shadow only."
                )
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
    lines.append(f"- AI explanation: **{'USED (explanation only)' if decision.get('ai_explanation_used') else 'NOT NEEDED / NOT AVAILABLE'}**")
    lines.append("- Exact legality, affordability, lineup, chip eligibility and projection arithmetic were validated after deterministic selection.")
    return "\n".join(lines)
