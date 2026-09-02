from __future__ import annotations
from collections import Counter


def _transfer_pairs(plan):
    return tuple(sorted((int(t['out']), int(t['in'])) for t in (plan.get('transfers') or []) if t.get('in') is not None))


def _strength(frac: float) -> str:
    if frac >= .70:
        return 'STRONG'
    if frac >= .45:
        return 'MODERATE'
    return 'WEAK'


def transfer_signal_summary(plans, *, top_n=10, equivalence_only=False):
    """Summarize recurring transfer signals across the best candidate plans.

    This is intentionally descriptive rather than a new scoring layer. It helps
    distinguish a robust 'sell X' consensus from a weak 'replacement Y over Z'
    preference without giving the LLM any decision authority.
    """
    sample=list(plans or [])[:top_n]
    if equivalence_only:
        eq=[p for p in sample if p.get('within_equivalence_band')]
        if eq:
            sample=eq
    if not sample:
        return []
    outs=Counter(); pairs=Counter()
    for p in sample:
        seen_out=set()
        for t in p.get('transfers') or []:
            if t.get('in') is None: continue
            o,i=int(t['out']),int(t['in'])
            pairs[(o,i)] += 1
            seen_out.add(o)
        for o in seen_out:
            outs[o]+=1
    n=float(len(sample))
    rows=[]
    for (o,i),count in pairs.most_common():
        pair_frac=count/n
        out_frac=outs[o]/n
        rows.append({
            'out':o,'in':i,'pair_frequency':round(pair_frac,3),
            'sell_frequency':round(out_frac,3),
            'pair_strength':_strength(pair_frac),
            'sell_strength':_strength(out_frac),
            'sample_plans':len(sample),
        })
    return rows


def deterministic_decision(plans, cfg, *, v2_v3=None, news=None, elite=None):
    """Choose the production plan deterministically.

    `cluster_sort` has already applied the configured equivalence-band
    robustness/flexibility policy. Therefore plans[0] is the production choice;
    this function only creates auditable report metadata around that choice.
    """
    if not plans:
        raise ValueError('No optimizer plans supplied')
    chosen=plans[0]
    alt=plans[1] if len(plans)>1 else None
    alt_margin=float(cfg.get('alternative_margin_points',2.0))
    if alt and abs(float(chosen['optimizer_score'])-float(alt['optimizer_score'])) > alt_margin:
        alt=None
    sep=(float(chosen['optimizer_score'])-float(plans[1]['optimizer_score'])) if len(plans)>1 else 9.0
    eq=float(cfg.get('optimizer',{}).get('near_tie_cluster_width_points',.75))
    inside=sep <= eq
    if inside:
        reason=(
            "The best options are too close to separate confidently on projected points. "
            "This plan is preferred because it keeps the safer overall setup: no unnecessary hit, useful money in the bank, and good flexibility for the next move."
        )
    else:
        reason=(
            f"This plan has a clearer projected advantage over the next option ({sep:.2f} points in the model). "
            "The choice is made by the FPL model; AI is only used to explain it when helpful."
        )
    chip=chosen.get('chip')
    if chip:
        chip_reason=f"Deterministic chip policy selected {chip}. Wildcard/Free Hit remain subject to their configured production authority policy."
    else:
        chip_reason="No production chip is selected; preserve chips unless the deterministic chip policy identifies a sufficiently strong opportunity."
    news=news or {}
    elite=elite or {}
    return {
        'plan_id':chosen['plan_id'],
        'alternative_plan_id':alt.get('plan_id') if alt else None,
        'confidence':'LOW',  # replaced later by recommendation_confidence
        'executive_reasoning':reason,
        'elite_signal':('Elite-manager signal is secondary and did not choose the production plan.' if elite.get('status') not in {'disabled','unavailable'} else 'Elite-manager signal neutral/unavailable; no adjustment applied.'),
        'chip_reasoning':chip_reason,
        'news_summary':([] if news.get('status')=='OK' else [f"News research status: {news.get('status','unknown')}; treat close calls and minutes estimates more cautiously."]),
        'risks':[],
        'decision_authority':'deterministic',
        'equivalence_band':inside,
        'separation':round(sep,3),
        'transfer_signals':transfer_signal_summary(plans,top_n=10,equivalence_only=inside),
    }


def explanation_needed(decision, *, v2_v3=None, news=None, chosen=None, cfg=None):
    cfg=cfg or {}
    mode=str(cfg.get('ai',{}).get('explanation_mode','complex_only')).lower()
    if mode in {'off','disabled','false','none'}:
        return False
    if mode in {'always','on'}:
        return True
    v2_v3=v2_v3 or {}; news=news or {}; chosen=chosen or {}
    material_news=any(i.get('confidence') in {'HIGH','MEDIUM'} and i.get('status') in {'ruled_out','major_doubt','rotation_risk','role_change'} for i in news.get('items',[]))
    return bool(
        decision.get('equivalence_band')
        or v2_v3.get('label') in {'DIFFERENT_ROUTE','MATERIAL_DISAGREEMENT'}
        or material_news
        or float(chosen.get('hit_cost',0)) > 0
        or chosen.get('chip')
    )
