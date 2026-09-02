import unittest
from fpl_ai_manager.decision import deterministic_decision, explanation_needed, transfer_signal_summary
from fpl_ai_manager.explainer import build_explanation_packet
from fpl_ai_manager.render import render_report


def _plans():
    base_lu={'starters':list(range(1,12)),'bench':[12,13,14,15],'captain':1,'vice_captain':2}
    return [
        {'plan_id':'p1','optimizer_score':100.0,'bank_after':25,'hit_cost':0,'chip':None,'transfers':[{'out':20,'in':30,'sell':45,'buy':40},{'out':21,'in':31,'sell':65,'buy':60}],
         'lineup':base_lu,'metrics':{'gw1':55,'gw3':165,'gw6':330,'weighted':148},'within_equivalence_band':True,'equivalence_tiebreak':1.2,'squad_ids':list(range(1,16))},
        {'plan_id':'p2','optimizer_score':99.6,'bank_after':15,'hit_cost':0,'chip':None,'transfers':[{'out':20,'in':32,'sell':45,'buy':50},{'out':21,'in':31,'sell':65,'buy':60}],
         'lineup':base_lu,'metrics':{'gw1':55,'gw3':164,'gw6':329,'weighted':147.5},'within_equivalence_band':True,'equivalence_tiebreak':1.0,'squad_ids':list(range(1,16))},
    ]


def test_deterministic_decision_always_selects_preordered_rank_one():
    cfg={'alternative_margin_points':2.0,'optimizer':{'near_tie_cluster_width_points':.75},'ai':{'explanation_mode':'complex_only'}}
    d=deterministic_decision(_plans(),cfg,v2_v3={'label':'DIFFERENT_ROUTE'},news={'status':'DEGRADED'},elite={})
    assert d['plan_id']=='p1'
    assert d['decision_authority']=='deterministic'
    assert d['alternative_plan_id']=='p2'


def test_complex_only_explanation_runs_for_near_tie_but_not_clear_week():
    cfg={'ai':{'explanation_mode':'complex_only'}}
    assert explanation_needed({'equivalence_band':True},v2_v3={'label':'AGREE'},news={'items':[]},chosen={'hit_cost':0},cfg=cfg)
    assert not explanation_needed({'equivalence_band':False},v2_v3={'label':'AGREE'},news={'items':[]},chosen={'hit_cost':0},cfg=cfg)


def test_explanation_packet_uses_player_names_for_routes():
    players={i:{'web_name':f'P{i}'} for i in range(1,40)}
    d=deterministic_decision(_plans(),{'alternative_margin_points':2,'optimizer':{'near_tie_cluster_width_points':.75}},news={},elite={})
    comp={'status':'available','label':'DIFFERENT_ROUTE','v2_transfers':[{'out':20,'in':30}],'v3_transfers':[{'out':20,'in':32}], 'v2_roll':False,'v3_roll':False}
    packet=build_explanation_packet(_plans()[0],_plans()[1],d,comp,players,{'status':'OK','items':[]},{})
    assert packet['selected']['transfers'][0]['out']=='P20'
    assert packet['v2_v3']['v3_transfers_named'][0]['in']=='P32'
    assert 'v3_first_action' not in packet['v2_v3']


def test_transfer_signal_distinguishes_sell_consensus_from_replacement():
    plans=_plans()+[
        {**_plans()[0],'plan_id':'p3','transfers':[{'out':20,'in':33},{'out':21,'in':31}]},
        {**_plans()[0],'plan_id':'p4','transfers':[{'out':20,'in':34}]},
    ]
    sig=transfer_signal_summary(plans,top_n=4)
    row=next(x for x in sig if x['out']==20 and x['in']==30)
    assert row['sell_strength']=='STRONG'
    assert row['pair_strength']=='WEAK'

class TestAlpha6Post1Corrections(unittest.TestCase):
    def test_explanation_packet_formats_bank_in_millions_and_hides_native_v3_score(self):
        from fpl_ai_manager.explainer import build_explanation_packet
        players={1:{'web_name':'Out'},2:{'web_name':'In'}}
        chosen={'plan_id':'p','transfers':[{'out':1,'in':2,'sell':45,'buy':40}], 'optimizer_score':10.0,'bank_after':25,'hit_cost':0,'chip':None}
        comparison={'status':'available','v2_optimizer_score':130.95,'v3_path_score':110.88,'v2_transfers':[],'v3_transfers':[],
                    'common_basis':{'status':'available','horizon_gws':3,'objective':'same','v2_score':100,'v3_score':101,'delta_v3_minus_v2':1,
                                    'v2_first_gw_score':50,'v3_first_gw_score':51,'v2_bank_after_first':25,'v3_bank_after_first':14}}
        packet=build_explanation_packet(chosen,None,{'transfer_signals':[]},comparison,players,{'items':[]},None)
        self.assertEqual(packet['selected']['bank_after'],'£2.5m')
        self.assertEqual(packet['selected']['transfers'][0]['sell_price'],'£4.5m')
        self.assertNotIn('v2_optimizer_score',packet['v2_v3'])
        self.assertNotIn('v3_path_score',packet['v2_v3'])
        self.assertEqual(packet['v2_v3']['common_basis']['v3_bank_after_first'],'£1.4m')

    def test_compare_marks_native_scores_not_comparable(self):
        from fpl_ai_manager.decision_compare import compare_v2_v3
        v2={'plan_id':'x','optimizer_score':130.95,'transfers':[]}
        v3=[{'score':110.88,'first_action':{'roll':True,'transfers':[]},'steps':[]}]
        c=compare_v2_v3(v2,v3)
        self.assertFalse(c['native_scores_comparable'])
        self.assertIn('different objectives',c['native_score_note'])

class TestAlpha6Post2Corrections(unittest.TestCase):
    def test_email_html_is_flat_and_subjects_are_unique_by_run(self):
        from datetime import datetime, timezone
        from fpl_ai_manager.emailer import html_body, _unique_subject
        body='# Title\n\n## Transfers\n- A → B\n\n## Starting XI\n- Player'
        rendered=html_body(body,datetime(2026,9,2,2,0,tzinfo=timezone.utc))
        self.assertNotIn('<details',rendered.lower())
        self.assertNotIn('<summary',rendered.lower())
        self.assertIn('<h2>Transfers</h2>',rendered)
        self.assertIn('<h2>Starting XI</h2>',rendered)
        a=_unique_subject('FPL GW3 Preview Recommendation',datetime(2026,9,2,2,0,tzinfo=timezone.utc))
        b=_unique_subject('FPL GW3 Preview Recommendation',datetime(2026,9,2,3,0,tzinfo=timezone.utc))
        self.assertNotEqual(a,b)

    def test_explainer_common_basis_keeps_explicit_gw_list(self):
        from fpl_ai_manager.explainer import build_explanation_packet
        players={1:{'web_name':'A'},2:{'web_name':'B'}}
        chosen={'plan_id':'p','transfers':[{'out':1,'in':2,'sell':45,'buy':40}], 'optimizer_score':10,'bank_after':25,'hit_cost':0,'chip':None}
        comparison={'status':'available','v2_transfers':[],'v3_transfers':[],
                    'common_basis':{'status':'available','horizon_gws':3,'evaluated_gws':[3,4,5],'objective':'same',
                                    'v2_score':160,'v3_score':161,'delta_v3_minus_v2':1,'v2_first_gw_score':55,'v3_first_gw_score':55.1,
                                    'v2_bank_after_first':25,'v3_bank_after_first':19,
                                    'v2_steps':[{'gw':3,'net_score':55},{'gw':4,'net_score':54},{'gw':5,'net_score':53}],
                                    'v3_steps':[{'gw':3,'net_score':55.1},{'gw':4,'net_score':54.2},{'gw':5,'net_score':53.3}]}}
        packet=build_explanation_packet(chosen,None,{'transfer_signals':[]},comparison,players,{'items':[]},None)
        cb=packet['v2_v3']['common_basis']
        self.assertEqual(cb['evaluated_gws'],[3,4,5])
        self.assertEqual(len(cb['v2_per_gw']),3)
        self.assertEqual(len(cb['v3_per_gw']),3)
