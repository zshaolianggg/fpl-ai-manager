import unittest
from fpl_ai_manager.state import (
    derive_sell_price,
    season_start_price,
    permanent_transfer_purchase_prices,
    reconstruct_purchase_price,
    load_public_state,
)


class FakeClient:
    def __init__(self, picks, transfers=None, chips=None):
        self._picks = picks
        self._transfers = transfers or []
        self._chips = chips or []

    def entry(self, team_id):
        return {"id": team_id, "last_deadline_bank": 5, "last_deadline_value": 1000}

    def history(self, team_id):
        return {"current": [], "chips": self._chips}

    def picks(self, team_id, gw):
        return {"picks": self._picks, "entry_history": {"bank": 5}}

    def transfers(self, team_id):
        return self._transfers


class PublicPriceReconstructionTests(unittest.TestCase):
    def test_start_price_from_bootstrap(self):
        self.assertEqual(season_start_price({"now_cost": 47, "cost_change_start": 2}), 45)

    def test_latest_permanent_transfer_in_is_purchase_basis(self):
        transfers = [
            {"event": 2, "element_in": 8, "element_in_cost": 50, "time": "2026-08-20T01:00:00Z"},
            {"event": 3, "element_in": 8, "element_in_cost": 52, "time": "2026-08-27T01:00:00Z"},
        ]
        self.assertEqual(permanent_transfer_purchase_prices(transfers, [])[8], 52)

    def test_free_hit_transfer_does_not_reset_purchase_basis(self):
        transfers = [
            {"event": 2, "element_in": 8, "element_in_cost": 50, "time": "2026-08-20T01:00:00Z"},
            {"event": 5, "element_in": 8, "element_in_cost": 56, "time": "2026-09-10T01:00:00Z"},
        ]
        prices = permanent_transfer_purchase_prices(transfers, [{"name": "freehit", "event": 5}])
        self.assertEqual(prices[8], 50)

    def test_reconstruct_held_since_gw1(self):
        purchase, basis = reconstruct_purchase_price(8, {"now_cost": 47, "cost_change_start": 2}, {})
        self.assertEqual((purchase, basis), (45, "season_start_price"))
        self.assertEqual(derive_sell_price(purchase, 47), 46)

    def test_public_picks_without_private_price_fields_are_actionable(self):
        picks = [{"element": i, "position": i, "is_captain": i == 1} for i in range(1, 16)]
        players = {
            i: {"id": i, "web_name": f"P{i}", "now_cost": 50 + i, "cost_change_start": 1}
            for i in range(1, 16)
        }
        state = load_public_state(FakeClient(picks), 123, 2, players)
        self.assertTrue(state["actionable"])
        self.assertEqual(len(state["squad"]), 15)
        self.assertTrue(all(x["price_basis"] == "season_start_price" for x in state["squad"]))


if __name__ == "__main__":
    unittest.main()
