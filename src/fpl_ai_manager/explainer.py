from __future__ import annotations
import json, os
try:
    from openai import OpenAI
except ImportError:
    OpenAI=None

EXPLAIN_SCHEMA={
    'type':'json_schema','name':'fpl_explanation','strict':True,
    'schema':{'type':'object','additionalProperties':False,
      'properties':{
        'executive_reasoning':{'type':'string'},
        'v2_v3_note':{'type':'string'},
        'risk_note':{'type':'string'},
      },
      'required':['executive_reasoning','v2_v3_note','risk_note']}
}

SYSTEM="""You explain an already-final Fantasy Premier League recommendation to a casual or beginner FPL player.
You have ZERO decision authority. Never change the selected plan, transfers, captain, vice-captain, bench, chip, bank, or prices. Never invent facts.
Use player names supplied in the packet, never raw player IDs. All money is already formatted as GBP millions.
Write in plain English. Avoid internal engineering terms such as optimizer_score, common_basis, pair_frequency, equivalence band, utility, objective, or path score. Translate them instead:
- equivalence band -> "the options are too close to call on projected points"
- common_basis -> "the same multi-gameweek comparison"
- pair_frequency -> "how often the move appears in the best plans"
- V2/V3 -> "the weekly model" and "the future-planning model"
Never compare native V2 optimizer_score with native V3 path_score. If the same-GW comparison is available, describe only the practical difference and whether it is meaningful.
Keep executive_reasoning to 2-4 short sentences. Explain what to do, why it helps, and what the main uncertainty is. Do not quote database field names.
If news is degraded, simply say fresh team news was limited, so close calls should be treated cautiously."""


def build_explanation_packet(chosen, alternative, decision, comparison, players_by_id, news, chip_shadow):
    def name(pid):
        row=players_by_id.get(int(pid),{}) if pid is not None else {}
        return row.get('web_name') or row.get('name') or f'player {pid}'
    def money(tenths):
        if tenths is None: return None
        return f"£{float(tenths)/10:.1f}m"
    def tx(plan):
        return [{'out':name(t['out']),'in':name(t['in']),'sell_price':money(t.get('sell')),'buy_price':money(t.get('buy'))} for t in (plan or {}).get('transfers',[])]
    comp=dict(comparison or {})
    comp['v2_transfers_named']=[{'out':name(t['out']),'in':name(t['in'])} for t in comp.get('v2_transfers',[])]
    comp['v3_transfers_named']=[{'out':name(t['out']),'in':name(t['in'])} for t in comp.get('v3_transfers',[])]
    comp['v3_future_steps_named']=[{
        **{k:step.get(k) for k in ('gw','roll','chip','hit_cost','free_transfers_after')},
        'bank_after':money(step.get('bank_after')),
        'transfers':[{'out':name(t['out']),'in':name(t['in'])} for t in step.get('transfers',[])]
    } for step in comp.get('v3_future_steps',[])[:3]]
    # Native V2/V3 scores are not comparable; keep them out of explanatory prose.
    comp.pop('v2_optimizer_score',None); comp.pop('v3_path_score',None)
    comp.pop('v3_first_action',None); comp.pop('v3_planner_diagnostics',None)
    comp['native_scores_comparable']=False
    cb=comp.get('common_basis') or {}
    if cb.get('status')=='available':
        comp['common_basis']={
            'status':'available','horizon_gws':cb.get('horizon_gws'),'evaluated_gws':cb.get('evaluated_gws'),'objective':cb.get('objective'),
            'v2_score':cb.get('v2_score'),'v3_score':cb.get('v3_score'),'delta_v3_minus_v2':cb.get('delta_v3_minus_v2'),
            'v2_first_gw_score':cb.get('v2_first_gw_score'),'v3_first_gw_score':cb.get('v3_first_gw_score'),
            'v2_bank_after_first':money(cb.get('v2_bank_after_first')),'v3_bank_after_first':money(cb.get('v3_bank_after_first')),
            'v2_per_gw':[{'gw':x.get('gw'),'net_score':x.get('net_score')} for x in (cb.get('v2_steps') or [])],
            'v3_per_gw':[{'gw':x.get('gw'),'net_score':x.get('net_score')} for x in (cb.get('v3_steps') or [])],
        }
    elif cb:
        comp['common_basis']={'status':'unavailable','reason':cb.get('reason')}
    sig=[]
    for s in decision.get('transfer_signals',[])[:8]:
        sig.append({**s,'out_name':name(s['out']),'in_name':name(s['in'])})
    alt={}
    if alternative:
        alt={'plan_id':alternative.get('plan_id'),'transfers':tx(alternative),'optimizer_score':alternative.get('optimizer_score'),'bank_after':money(alternative.get('bank_after')),'hit_cost':alternative.get('hit_cost')}
    material=[{k:i.get(k) for k in ('player','status','confidence','claim','source_title')} for i in (news or {}).get('items',[]) if i.get('confidence') in {'HIGH','MEDIUM'}][:6]
    return {
        'selected':{'plan_id':chosen.get('plan_id'),'transfers':tx(chosen),'optimizer_score':chosen.get('optimizer_score'),'bank_after':money(chosen.get('bank_after')),'hit_cost':chosen.get('hit_cost'),'chip':chosen.get('chip')},
        'alternative':alt,
        'equivalence_band':decision.get('equivalence_band'),'separation':decision.get('separation'),
        'transfer_signals':sig,
        'v2_v3':comp,
        'news_status':(news or {}).get('status'),'material_news':material,
        'chip_shadow':{'status':(chip_shadow or {}).get('status'),'baseline_non_chip_score':(chip_shadow or {}).get('baseline_non_chip_score')},
    }


def explain(packet, *, model=None, timeout=25):
    raw=json.dumps(packet,separators=(',',':'),default=str)
    print(f"::notice::AI explanation input chars={len(raw)}",flush=True)
    try:
        if OpenAI is None: raise RuntimeError('openai package unavailable')
        client=OpenAI(api_key=os.environ['OPENAI_API_KEY'],max_retries=0,timeout=float(timeout))
        resp=client.responses.create(model=model or os.getenv('OPENAI_EXPLANATION_MODEL') or os.getenv('OPENAI_MODEL','gpt-5-mini'),instructions=SYSTEM,input=raw,text={'format':EXPLAIN_SCHEMA})
        return json.loads(resp.output_text),resp
    except Exception as exc:
        print(f"::warning::Optional AI explanation unavailable: {type(exc).__name__}: {exc}",flush=True)
        return None,None
