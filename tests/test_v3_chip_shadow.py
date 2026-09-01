import unittest

from fpl_ai_manager.chips import augment_with_chip_plans, opportunity_map
from fpl_ai_manager.multigw import ManagerState, plan_multigw
from fpl_ai_manager.optimizer import plan_metrics
from test_v3_multigw import make_world


class ChipShadowPolicyTests(unittest.TestCase):
    def test_force_first_chip_constrains_shadow_path(self):
        players, projections, proj = make_world()
        for pid in (16, 17):
            proj[pid]["per_gw"][1] = 20.0
            proj[pid]["gw1"] = 20.0
        ledger = tuple((p, 50) for p in range(1, 16))
        state = ManagerState(1, tuple(range(1, 16)), 0, 1, ledger, ledger, False, True)
        paths = plan_multigw(
            state, players, projections, proj,
            planning_horizon=1, candidate_per_position=6, beam_width=80,
            max_transfers_per_gw=2, top_n=1, include_chips=True,
            force_first_chip="freehit", runtime_budget_seconds=5,
        )
        self.assertTrue(paths)
        self.assertEqual(paths[0]["first_action"]["chip"], "freehit")
        self.assertEqual(paths[0]["planner_diagnostics"]["forced_first_chip"], "freehit")

    def test_wc_fh_are_excluded_from_production_plan_list(self):
        players_by_id, projections, proj = make_world()
        squad = list(range(1, 16))
        weights = {"gw1": .45, "gw3": .35, "gw6": .20}
        metrics = plan_metrics(squad, proj, 2, weights, .2)
        base = {
            "transfers": [], "squad_ids": squad, "bank_after": 0,
            "hit_cost": 0, "chip": None, "metrics": metrics,
            "flexibility_adjustment": 0.0, "optimizer_score": metrics["weighted"],
            "lineup": metrics["lineups"][2], "reason_flags": ["ROLL"], "plan_id": "base",
        }
        cfg = {
            "projection_weights": weights, "bench_weight": .2, "flexibility_cap_points": 2.0,
            "optimizer": {"top_plans": 20},
            "chips": {
                "free_hit_early_threshold": 1.0, "free_hit_late_threshold": 1.0,
                "wildcard_early_threshold": 1.0, "wildcard_late_threshold": 1.0,
                "bench_boost_early_threshold": 99.0, "bench_boost_late_threshold": 99.0,
                "triple_captain_normal_points_target": 99.0,
                "future_opportunity_reserve_factor": .9,
                "minimum_opportunity_edge_points": 99.0,
                "confirmed_structure_reserve_points": 2.0,
                "max_structure_reserve_points": 6.0,
                "production_wildcard_freehit": False,
            },
        }
        state = {
            "squad": [{"player_id": p, "selling_price": 50} for p in squad],
            "bank": 0,
            "chips_available": {"wildcard": True, "freehit": True, "bboost": False, "3xc": False},
        }
        chip_map = opportunity_map([], {}, 2, cfg)
        out = augment_with_chip_plans(base and [base], state, list(players_by_id.values()), players_by_id, proj, 2, cfg, chip_map)
        self.assertTrue(out)
        self.assertTrue(all(p.get("chip") not in {"wildcard", "freehit"} for p in out))
        self.assertEqual(chip_map["wc_fh_policy"]["production"], "shadow_only")


if __name__ == "__main__":
    unittest.main()
