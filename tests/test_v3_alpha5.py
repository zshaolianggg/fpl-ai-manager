import unittest
from datetime import datetime, timezone, timedelta

from fpl_ai_manager.lineup import expected_auto_sub_points, gw_points_conditional_on_appearance
from fpl_ai_manager.optimizer import cluster_sort
from fpl_ai_manager.decision_compare import compare_v2_v3
from fpl_ai_manager.backtest.snapshots import validate_no_future_leakage, LeakageError
from fpl_ai_manager.chips import evaluate_wc_fh_shadow, opportunity_map
from test_v3_multigw import make_world


class AutoSubCorrectnessTests(unittest.TestCase):
    def test_conditional_points_do_not_double_discount_appearance(self):
        row={"per_gw":{3:4.0},"fixtures":[{"gw":3,"projection":{"p_appearance":.5}}],"minutes_projection":{"p_appearance":.5}}
        self.assertAlmostEqual(gw_points_conditional_on_appearance(row,3),8.0)

    def test_bench_player_with_zero_appearance_contributes_zero(self):
        players, projections, proj=make_world()
        starters=[(pid,proj[pid]["per_gw"][1]) for pid in [1,3,4,5,8,9,10,11,12,13,14]]
        bench=[2,6,7,15]
        proj[6]["fixtures"]=[{"gw":1,"projection":{"p_appearance":0.0}}]
        proj[6]["minutes_projection"]={"p_appearance":0.0}
        proj[6]["per_gw"][1]=20.0
        value=expected_auto_sub_points(starters,bench,proj,1)
        proj[6]["per_gw"][1]=0.0
        value_without=expected_auto_sub_points(starters,bench,proj,1)
        self.assertAlmostEqual(value,value_without,places=6)


class EquivalencePolicyTests(unittest.TestCase):
    def test_more_bank_can_win_inside_equivalence_band(self):
        players, projections, proj=make_world()
        squad=list(range(1,16))
        lu={"bench":[2,6,7,15],"captain":8}
        a={"optimizer_score":100.0,"squad_ids":squad,"bank_after":0,"hit_cost":0,"transfers":[{"out":8,"in":16}],"lineup":lu}
        b={"optimizer_score":99.6,"squad_ids":squad,"bank_after":30,"hit_cost":0,"transfers":[{"out":8,"in":16}],"lineup":lu}
        out=cluster_sort([a,b],proj,.75)
        self.assertIs(out[0],b)
        self.assertTrue(out[0]["equivalence_band_winner"])


class DecisionComparisonTests(unittest.TestCase):
    def test_roll_disagreement_is_material(self):
        v2={"plan_id":"x","optimizer_score":1,"transfers":[]}
        v3=[{"score":10,"first_action":{"roll":False,"transfers":[{"out":8,"in":16}]}}]
        c=compare_v2_v3(v2,v3)
        self.assertEqual(c["label"],"MATERIAL_DISAGREEMENT")
        self.assertFalse(c["same_first_action"])


class LeakageGuardTests(unittest.TestCase):
    def test_future_evidence_is_rejected(self):
        d=datetime(2026,9,5,10,tzinfo=timezone.utc)
        with self.assertRaises(LeakageError):
            validate_no_future_leakage({"deadline":d.isoformat(),"evidence":[{"published_at":(d+timedelta(minutes=1)).isoformat()}]})

    def test_pre_deadline_evidence_passes(self):
        d=datetime(2026,9,5,10,tzinfo=timezone.utc)
        validate_no_future_leakage({"deadline":d.isoformat(),"evidence":[{"published_at":(d-timedelta(minutes=1)).isoformat()}]})


class DirectChipShadowTests(unittest.TestCase):
    def test_shadow_directly_constructs_freehit_instead_of_forced_beam_discovery(self):
        players, projections, proj=make_world()
        # Make alternatives excellent in GW2 so a direct FH squad has something to find.
        for pid in (16,17):
            proj[pid]["per_gw"][2]=20.0
            proj[pid]["gw3"]+=8.0
        state={
            "mode":"managed","squad":[{"player_id":p,"selling_price":50,"purchase_price":50} for p in range(1,16)],
            "bank":0,"free_transfers":1,
            "chips_available":{"wildcard":True,"freehit":True,"bboost":False,"3xc":False},
        }
        cfg={
            "bench_weight":.2,"multigw":{"discount":.97},
            "chips":{
                "free_hit_early_threshold":1,"free_hit_late_threshold":1,"wildcard_early_threshold":1,"wildcard_late_threshold":1,
                "bench_boost_early_threshold":99,"bench_boost_late_threshold":99,"triple_captain_normal_points_target":99,
                "wc_fh_shadow":{"enabled":True,"planning_horizon":2,"candidate_per_position":6,"direct_chip_candidate_per_position":6,
                                "beam_width":30,"max_transfers_per_gw":2,"runtime_budget_seconds_per_run":5,
                                "preservation_reserve_factor":.5,"minimum_wildcard_preservation_points":1,
                                "minimum_freehit_preservation_points":1,"minimum_net_edge_points":0,"low_confidence_edge_multiplier":1},
            },
        }
        chip_map=opportunity_map([],{},2,cfg)
        result=evaluate_wc_fh_shadow(state,players,projections,proj,2,cfg,chip_map,news_status="OK",all_low=False)
        self.assertTrue(result["chips"]["freehit"]["evaluated"])
        self.assertEqual(result["chips"]["freehit"]["planner_diagnostics"]["construction"],"direct_chip")


if __name__=="__main__":
    unittest.main()
