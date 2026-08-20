
import unittest
from fpl_ai_manager.state import derive_sell_price,reconstruct_free_transfers,chip_availability
from fpl_ai_manager.elite import current_weight
from fpl_ai_manager.validator import validate_squad
from fpl_ai_manager.schedule import classify_window
from datetime import datetime,timezone

class CoreTests(unittest.TestCase):
    def test_sell_price_profit(self):
        self.assertEqual(derive_sell_price(70,75),72)
    def test_sell_price_loss(self):
        self.assertEqual(derive_sell_price(70,68),68)
    def test_ft_roll(self):
        rows=[{"event":2,"event_transfers":0,"event_transfers_cost":0}]
        ft,w=reconstruct_free_transfers(rows,[],3)
        self.assertEqual(ft,2); self.assertFalse(w)
    def test_ft_hit(self):
        rows=[{"event":2,"event_transfers":2,"event_transfers_cost":4}]
        ft,w=reconstruct_free_transfers(rows,[],3)
        self.assertEqual(ft,1)
    def test_wc_preserves_ft(self):
        rows=[{"event":2,"event_transfers":10,"event_transfers_cost":0}]
        ft,w=reconstruct_free_transfers(rows,[{"name":"wildcard","event":2}],3)
        self.assertEqual(ft,2)
    def test_chip_gw1(self):
        a=chip_availability(1,[])
        self.assertFalse(a["wildcard"]); self.assertFalse(a["freehit"]); self.assertTrue(a["3xc"])
    def test_elite_ramp(self):
        self.assertEqual(current_weight(5),0)
        self.assertEqual(current_weight(8),.30)
        self.assertEqual(current_weight(14),.80)
    def test_sleep_safe(self):
        deadline="2026-08-23T00:00:00Z" # 08:00 Beijing
        now=datetime(2026,8,22,14,17,tzinfo=timezone.utc) # 22:17 Beijing
        kind,_,mode=classify_window(deadline,(23,25),(2,3.5),now=now)
        self.assertEqual((kind,mode),("final","sleep_safe"))

if __name__=="__main__": unittest.main()
