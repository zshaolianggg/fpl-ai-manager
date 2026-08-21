import unittest

from fpl_ai_manager.minutes import project_minutes
from fpl_ai_manager.optimizer import _gw1_structural_diagnostics, _gw1_v3_score
from fpl_ai_manager.render import render_report


def prow(pid, pos, price=50, pts=3.0, p_app=.98):
    return {
        "player_id": pid, "position": pos, "price": price, "team_id": (pid % 5)+1,
        "expected_minutes": 80, "confidence": "HIGH", "status": "a",
        "per_gw": {1: pts, 2: pts, 3: pts, 4: pts, 5: pts, 6: pts, 7: pts, 8: pts},
        "minutes_projection": {"p_appearance": p_app},
        "gw1": pts, "gw3": pts*3, "gw6": pts*6,
    }


class RolePriorTests(unittest.TestCase):
    def test_established_premium_anchor_gets_strong_start_prior(self):
        player={"element_type":4,"now_cost":155,"selected_by_percent":"65","status":"a","web_name":"Anchor"}
        prior={"time":2550,"games":32}
        p=project_minutes(player,[],prior,{},None)
        self.assertGreaterEqual(p.p_start,.90)
        self.assertIn("premium_anchor_role_prior", p.reasons)

    def test_generic_unknown_does_not_get_nailed_prior(self):
        player={"element_type":4,"now_cost":60,"selected_by_percent":"2","status":"a","web_name":"Unknown"}
        p=project_minutes(player,[],{}, {},None)
        self.assertLess(p.p_start,.85)


class GW1StructureTests(unittest.TestCase):
    def make_projection(self):
        positions=[1,1]+[2]*5+[3]*5+[4]*3
        proj={pid:prow(pid,pos,price=50,pts=4.0) for pid,pos in enumerate(positions,1)}
        proj[15]=prow(15,4,price=75,pts=1.0)  # expensive weak forward, should be deep bench
        return proj

    def test_expensive_deep_bench_is_flagged(self):
        proj=self.make_projection()
        met={"lineups":{1:{
            "starters":list(range(1,12)),
            "bench":[2,12,13,15],
            "expected_auto_sub_points":.4,
            "probabilistic_score":50.0,
        }}}
        d=_gw1_structural_diagnostics(list(range(1,16)),met,proj,1)
        self.assertIn(15,d["expensive_deep_bench"])

    def test_deep_bench_capital_reduces_near_tie_score(self):
        proj=self.make_projection()
        base_lu={"starters":list(range(1,12)),"bench":[2,12,13,15],"expected_auto_sub_points":.4,"probabilistic_score":50.0}
        met={"lineups":{i:dict(base_lu, probabilistic_score=50.0) for i in range(1,9)}}
        cfg={"projection_weights":{"gw1":.45,"gw3":.35,"gw6":.2},"flexibility_cap_points":2.0,
             "gw1":{"expensive_deep_bench_penalty":.45,"dormant_capital_free_index":17.0,
                    "dormant_capital_penalty_per_index":.08,"dormant_capital_penalty_cap":1.5}}
        score,diag,_=_gw1_v3_score(list(range(1,16)),met,proj,1,cfg["projection_weights"],0,cfg)
        self.assertGreater(len(diag["expensive_deep_bench"]),0)
        # Core is 50*(.45 + 3*.35 + 6*.2)=135; structure should pull below that.
        self.assertLess(score,135.0)


class ReportingTests(unittest.TestCase):
    def test_report_names_production_engine_and_structural_flag(self):
        players={i:{"web_name":f"P{i}"} for i in range(1,16)}
        positions=[1,1]+[2]*5+[3]*5+[4]*3
        proj={i:prow(i,pos,price=(75 if i==15 else 50),pts=3.0) for i,pos in enumerate(positions,1)}
        plan={"squad_ids":list(range(1,16)),"bank_after":0,"transfers":[],"chip":None,"hit_cost":0,
              "metrics":{"gw1":40,"gw3":120,"gw6":240,"weighted":100},
              "lineup":{"starters":[1,3,4,5,8,9,10,11,12,13,14],"bench":[2,6,7,15],"captain":13,"vice_captain":14},
              "structural_diagnostics":{"starting_cost_tenths":550,"bench_cost_tenths":225,"expected_auto_sub_points":.3,"expensive_deep_bench":[15]}}
        decision={"confidence":"LOW","executive_reasoning":"Selected by V3.","chip_reasoning":"Hold.","elite_signal":"Unavailable.","news_summary":[],"risks":[],"alternative_plan_id":None}
        text=render_report(1,"final","standard","gw1_initial_build",plan,decision,players,proj,decision_audit={"production_engine":"V3 GW1 probabilistic/structural reranker"})
        self.assertIn("V3 GW1 probabilistic/structural reranker",text)
        self.assertIn("expensive deep-bench capital",text)
        self.assertNotIn("20%-weighted bench",text)


if __name__ == "__main__":
    unittest.main()
