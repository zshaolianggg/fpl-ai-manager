import unittest

from fpl_ai_manager.captaincy import recommend_captaincy, captain_pair_value, candidate
from fpl_ai_manager.chips import chip_opportunity_costs


def row(pid, pos, values, p_app=.98, variance=4.0):
    fixtures=[]
    for gw, pts in values.items():
        fixtures.append({"gw": gw, "projection": {
            "p_appearance": p_app, "variance": variance,
            "p10": max(0.0, pts-2.0), "p90": pts+3.0,
            "p_10_plus": min(1.0, pts/15.0),
        }})
    return {
        "player_id": pid, "position": pos, "price": 80,
        "expected_minutes": 82, "confidence": "HIGH", "status": "a",
        "per_gw": {int(k): float(v) for k,v in values.items()},
        "fixtures": fixtures, "minutes_projection": {"p_appearance": p_app},
    }


class CaptaincyEngineTests(unittest.TestCase):
    def test_joint_pair_values_vice_when_captain_can_miss(self):
        cap = candidate(row(1,3,{5:9.0},p_app=.70),5)
        strong_vice = candidate(row(2,4,{5:8.0},p_app=.99),5)
        weak_vice = candidate(row(3,4,{5:3.0},p_app=.99),5)
        self.assertGreater(captain_pair_value(cap,strong_vice), captain_pair_value(cap,weak_vice))

    def test_probabilistic_recommendation_returns_distribution(self):
        proj = {
            1: row(1,3,{5:9.0},p_app=.92,variance=5.0),
            2: row(2,4,{5:8.5},p_app=.99,variance=3.0),
            3: row(3,2,{5:10.0},p_app=.99,variance=3.0),
        }
        rec = recommend_captaincy([1,2,3],proj,5)
        self.assertIn(rec["captain"], {1,2,3})
        self.assertNotEqual(rec["captain"], rec["vice_captain"])
        self.assertTrue(rec["candidates"])
        self.assertIn("p90", rec["candidates"][0])
        # Defender is not auto-selected on a marginal raw edge.
        self.assertNotEqual(rec["captain"], 3)


class ChipOpportunityTests(unittest.TestCase):
    def test_triple_captain_waits_for_better_future_window(self):
        # Legal 15-man shape; attacker 13 has a much stronger GW6 than GW5.
        positions=[1,1]+[2]*5+[3]*5+[4]*3
        proj={}
        for pid,pos in enumerate(positions,1):
            vals={5:2.0,6:2.0}
            if pid==13:
                vals={5:7.0,6:14.0}
            proj[pid]=row(pid,pos,vals,p_app=.99)
        cfg={"bench_weight":.2,"chips":{"future_opportunity_reserve_factor":.9,"minimum_opportunity_edge_points":1.0}}
        opp=chip_opportunity_costs(list(range(1,16)),proj,5,cfg)
        self.assertLess(opp["triple_captain"]["net"], 0)
        self.assertGreater(opp["triple_captain"]["future_best"], opp["triple_captain"]["current"])

    def test_triple_captain_can_fire_when_current_window_dominates(self):
        positions=[1,1]+[2]*5+[3]*5+[4]*3
        proj={}
        for pid,pos in enumerate(positions,1):
            vals={5:2.0,6:2.0}
            if pid==13:
                vals={5:15.0,6:6.0}
            proj[pid]=row(pid,pos,vals,p_app=.99)
        cfg={"bench_weight":.2,"chips":{"future_opportunity_reserve_factor":.9,"minimum_opportunity_edge_points":1.0}}
        opp=chip_opportunity_costs(list(range(1,16)),proj,5,cfg)
        self.assertGreater(opp["triple_captain"]["net"], 1.0)
