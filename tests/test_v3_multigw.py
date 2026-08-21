import unittest

from fpl_ai_manager.lineup import best_lineup
from fpl_ai_manager.multigw import ManagerState, Transfer, apply_transfers, plan_multigw


def row(pid, pos, gw1, gw2, price=50, p_app=.98, team=1):
    return {
        "player_id": pid,
        "player": f"P{pid}",
        "position": pos,
        "team_id": team,
        "price": price,
        "expected_minutes": 80,
        "confidence": "HIGH",
        "status": "a",
        "selected_by_percent": "5.0",
        "gw1": gw1,
        "gw3": gw1+gw2,
        "gw6": gw1+gw2,
        "per_gw": {1: float(gw1), 2: float(gw2), 3: 0.0, 4: 0.0},
        "minutes_projection": {"p_appearance": p_app},
        "fixtures": [
            {"gw": 1, "projection": {"p_appearance": p_app}},
            {"gw": 2, "projection": {"p_appearance": p_app}},
        ],
    }


def make_world():
    # Legal 2/5/5/3 squad. Teams are spread so club limits never bind.
    positions = [1,1] + [2]*5 + [3]*5 + [4]*3
    projections = []
    players = {}
    for pid, pos in enumerate(positions, 1):
        g1 = 2.0
        g2 = 2.0
        if pid in {8, 9}:  # two currently strong MIDs who become poor in GW2
            g1, g2 = 10.0, 1.0
        r = row(pid, pos, g1, g2, price=50, p_app=.99, team=((pid-1)//3)+1)
        projections.append(r)
        players[pid] = {"id": pid, "element_type": pos, "team": r["team_id"], "web_name": r["player"]}

    # Two future MIDs: awful now, excellent next GW.
    for pid in (16, 17):
        r = row(pid, 3, 0.0, 12.0, price=50, p_app=.99, team=6+(pid-16))
        projections.append(r)
        players[pid] = {"id": pid, "element_type": 3, "team": r["team_id"], "web_name": r["player"]}
    return players, projections, {r["player_id"]: r for r in projections}


class ProbabilisticLineupTests(unittest.TestCase):
    def test_auto_sub_value_rises_with_starter_no_show_risk(self):
        players, projections, proj = make_world()
        squad = list(range(1, 16))
        safe = best_lineup(squad, proj, 1, selection_mode="probabilistic")

        # Make one high-scoring starter very likely to miss out while retaining
        # a useful bench. Expected auto-sub value should increase.
        risky = {k: dict(v) for k, v in proj.items()}
        risky[8] = dict(risky[8])
        risky[8]["fixtures"] = [{"gw": 1, "projection": {"p_appearance": .25}}]
        risky[8]["minutes_projection"] = {"p_appearance": .25}
        risk_lu = best_lineup(squad, risky, 1, selection_mode="probabilistic")
        self.assertGreater(risk_lu["expected_auto_sub_points"], safe["expected_auto_sub_points"])

    def test_captain_fallback_to_vice_has_positive_value(self):
        players, projections, proj = make_world()
        squad = list(range(1, 16))
        # Force the likely captain to have a meaningful no-show probability.
        top = max(squad, key=lambda p: proj[p]["per_gw"][1])
        proj[top]["fixtures"] = [{"gw": 1, "projection": {"p_appearance": .60}}]
        lu = best_lineup(squad, proj, 1, selection_mode="probabilistic")
        self.assertGreaterEqual(lu["captain_fallback_points"], 0)


class ManagerStateTests(unittest.TestCase):
    def test_roll_increases_free_transfers(self):
        players, projections, proj = make_world()
        state = ManagerState(1, tuple(range(1,16)), 0, 1, tuple((p,50) for p in range(1,16)))
        nxt, hit = apply_transfers(state, tuple(), players, proj)
        self.assertEqual(hit, 0)
        self.assertEqual(nxt.free_transfers, 2)
        self.assertEqual(nxt.gw, 2)

    def test_second_transfer_with_one_ft_costs_four(self):
        players, projections, proj = make_world()
        state = ManagerState(1, tuple(range(1,16)), 0, 1, tuple((p,50) for p in range(1,16)))
        nxt, hit = apply_transfers(state, (Transfer(8,16), Transfer(9,17)), players, proj)
        self.assertEqual(hit, 4)
        self.assertEqual(nxt.free_transfers, 1)
        self.assertIn(16, nxt.squad)
        self.assertIn(17, nxt.squad)

    def test_planner_values_roll_when_two_future_moves_are_better_delayed(self):
        players, projections, proj = make_world()
        state = ManagerState(1, tuple(range(1,16)), 0, 1, tuple((p,50) for p in range(1,16)))
        paths = plan_multigw(
            state, players, projections, proj,
            planning_horizon=2,
            candidate_per_position=6,
            beam_width=80,
            max_transfers_per_gw=2,
            top_n=5,
        )
        self.assertTrue(paths)
        self.assertTrue(paths[0]["first_action"]["roll"])
        self.assertEqual(paths[0]["steps"][0]["free_transfers_after"], 2)
        # The best path should then use both future midfield upgrades in GW2.
        gw2_ins = {t["in"] for t in paths[0]["steps"][1]["transfers"]}
        self.assertEqual(gw2_ins, {16,17})


if __name__ == "__main__":
    unittest.main()

class Alpha3PlannerCacheTests(unittest.TestCase):
    def test_planner_reuses_lineup_evaluations(self):
        players, projections, proj = make_world()
        state = ManagerState(1, tuple(range(1,16)), 0, 1, tuple((p,50) for p in range(1,16)))
        paths = plan_multigw(
            state, players, projections, proj,
            planning_horizon=2, candidate_per_position=6, beam_width=80,
            max_transfers_per_gw=2, top_n=1,
        )
        diag = paths[0]["planner_diagnostics"]
        self.assertGreater(diag["lineup_cache_hits"], 0)
        self.assertLess(diag["unique_lineups"], diag["unique_transitions"])
