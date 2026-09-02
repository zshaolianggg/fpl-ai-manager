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

SYSTEM="""You explain an already-final Fantasy Premier League recommendation.
You have ZERO decision authority. Never change the selected plan, transfers, captain, vice-captain, bench, chip, bank, or prices. Never invent facts.
Use player names supplied in the packet, never raw player IDs in user-facing prose.
Explain why the deterministic plan was selected, especially equivalence-band flexibility or V2/V3 route differences. Treat tiny projection gaps as noise. Keep the explanation concise and practical. If news is degraded, say that this lowers confidence rather than implying negative news."""


def build_explanation_packet(chosen, alternative, decision, comparison, players_by_id, news, chip_shadow):
    def name(pid):
        row=players_by_id.get(int(pid),{}) if pid is not None else {}
        return row.get('web_name') or row.get('name') or f'player {pid}'
    def tx(plan):
        return [{'out':name(t['out']),'in':name(t['in']),'sell':t.get('sell'),'buy':t.get('buy')} for t in (plan or {}).get('transfers',[])]
    comp=dict(comparison or {})
    comp['v2_transfers_named']=[{'out':name(t['out']),'in':name(t['in'])} for t in comp.get('v2_transfers',[])]
    comp['v3_transfers_named']=[{'out':name(t['out']),'in':name(t['in'])} for t in comp.get('v3_transfers',[])]
    comp['v3_future_steps_named']=[{
        **{k:step.get(k) for k in ('gw','roll','chip','hit_cost','bank_after','free_transfers_after')},
        'transfers':[{'out':name(t['out']),'in':name(t['in'])} for t in step.get('transfers',[])]
    } for step in comp.get('v3_future_steps',[])[:3]]
    # Do not expose bulky raw V3 action structures to the explainer.
    comp.pop('v3_first_action',None); comp.pop('v3_planner_diagnostics',None)
    sig=[]
    for s in decision.get('transfer_signals',[])[:8]:
        sig.append({**s,'out_name':name(s['out']),'in_name':name(s['in'])})
    alt={}
    if alternative:
        alt={'plan_id':alternative.get('plan_id'),'transfers':tx(alternative),'optimizer_score':alternative.get('optimizer_score'),'bank_after':alternative.get('bank_after'),'hit_cost':alternative.get('hit_cost')}
    material=[{k:i.get(k) for k in ('player','status','confidence','claim','source_title')} for i in (news or {}).get('items',[]) if i.get('confidence') in {'HIGH','MEDIUM'}][:6]
    return {
        'selected':{'plan_id':chosen.get('plan_id'),'transfers':tx(chosen),'optimizer_score':chosen.get('optimizer_score'),'bank_after':chosen.get('bank_after'),'hit_cost':chosen.get('hit_cost'),'chip':chosen.get('chip')},
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
