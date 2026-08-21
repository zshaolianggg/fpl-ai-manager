import unittest

from fpl_ai_manager.multigw import (
    ManagerState, PlannerAction, Path, Transfer, apply_transfers,
    dominance_prune, plan_multigw, transition,
)
from fpl_ai_manager.prices import affordability_risk_for_buys, projected_price
from test_v3_multigw import make_world, row


class ChipStateTests(unittest.TestCase):
    def _state(self, *, wc=True, fh=True):
        return ManagerState(
            1, tuple(range(1, 16)), 0, 1, tuple((p, 50) for p in range(1, 16)),
            tuple((p, 50) for p in range(1, 16)), wc, fh,
        )

    def test_free_hit_is_temporary_and_preserves_ft_bank(self):
        players, projections, proj = make_world()
        state = self._state(wc=True, fh=True)
        chip_squad = tuple(sorted((set(state.squad) - {8}) | {16}))
        tr = transition(state, PlannerAction(chip="freehit", squad=chip_squad), players, proj)
        self.assertIsNotNone(tr)
        self.assertEqual(tr.state.squad, state.squad)
        self.assertEqual(tr.state.bank, state.bank)
        self.assertEqual(tr.state.free_transfers, 2)
        self.assertFalse(tr.state.freehit_available)
        self.assertTrue(tr.state.wildcard_available)

    def test_wildcard_is_permanent_and_preserves_ft(self):
        players, projections, proj = make_world()
        state = self._state(wc=True, fh=True)
        chip_squad = tuple(sorted((set(state.squad) - {8}) | {16}))
        tr = transition(state, PlannerAction(chip="wildcard", squad=chip_squad), players, proj)
        self.assertIsNotNone(tr)
        self.assertIn(16, tr.state.squad)
        self.assertNotIn(8, tr.state.squad)
        self.assertEqual(tr.state.free_transfers, 2)
        self.assertFalse(tr.state.wildcard_available)
        self.assertTrue(tr.state.freehit_available)

    def test_planner_can_choose_free_hit_as_real_action(self):
        players, projections, proj = make_world()
        # Make both temporary mids enormous in GW1 so FH can replace two players
        # without paying the hit that an ordinary two-transfer action would pay.
        for pid in (16, 17):
            proj[pid]["per_gw"][1] = 20.0
            proj[pid]["per_gw"][2] = 0.0
            proj[pid]["gw1"] = 20.0
            proj[pid]["gw3"] = 20.0
        state = self._state(wc=False, fh=True)
        paths = plan_multigw(
            state, players, projections, proj,
            planning_horizon=1, candidate_per_position=6, beam_width=80,
            max_transfers_per_gw=2, top_n=3, include_chips=True,
        )
        self.assertTrue(paths)
        self.assertEqual(paths[0]["first_action"]["chip"], "freehit")
        self.assertEqual(paths[0]["terminal_squad"], list(state.squad))


class DominanceTests(unittest.TestCase):
    def test_more_score_bank_and_ft_dominates_same_football_state(self):
        ledger = tuple((p, 50) for p in range(1, 16))
        base = dict(gw=2, squad=tuple(range(1,16)), sell_prices=ledger, purchase_prices=ledger,
                    wildcard_available=False, freehit_available=False)
        stronger = ManagerState(bank=5, free_transfers=2, **base)
        weaker = ManagerState(bank=3, free_transfers=1, **base)
        kept, removed = dominance_prune([
            Path(weaker, 9.0, []), Path(stronger, 10.0, [])
        ])
        self.assertEqual(removed, 1)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].state.bank, 5)


class PricePathTests(unittest.TestCase):
    def test_future_rise_can_make_delayed_transfer_unaffordable(self):
        players, projections, proj = make_world()
        proj[16]["price_path"] = {1: 50, 2: 51}
        ledger = tuple((p, 50) for p in range(1, 16))
        state = ManagerState(1, tuple(range(1, 16)), 0, 1, ledger, ledger)

        # Affordable before the rise.
        now = apply_transfers(state, (Transfer(8, 16),), players, proj)
        self.assertIsNotNone(now)

        # Roll one week; the same target is now £0.1m more expensive.
        rolled, _ = apply_transfers(state, tuple(), players, proj)
        self.assertEqual(rolled.gw, 2)
        self.assertEqual(projected_price(proj[16], 2), 51)
        later = apply_transfers(rolled, (Transfer(8, 16),), players, proj)
        self.assertIsNone(later)

    def test_optional_price_risk_is_bounded_and_transparent(self):
        r = row(99, 3, 5, 5, price=70)
        r["price_risk"] = {1: {"rise_probability": 0.8, "adverse_delta": 1}}
        risk = affordability_risk_for_buys([r], 1, bank_after=0)
        self.assertTrue(risk["at_risk"])
        self.assertEqual(risk["expected_adverse_tenths"], 0.8)
        self.assertEqual(risk["exposed_player_ids"], [99])


if __name__ == "__main__":
    unittest.main()
