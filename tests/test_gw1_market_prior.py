
import unittest
from fpl_ai_manager.optimizer import _gw1_market_prior
from fpl_ai_manager.lineup import best_lineup

class GW1PriorTests(unittest.TestCase):
    def test_market_prior_is_bounded(self):
        self.assertLessEqual(_gw1_market_prior({"selected_by_percent":"90","price":160,"position":4}),4.0)
    def test_high_owned_premium_gets_more_prior(self):
        a={"selected_by_percent":"75","price":155,"position":4}
        b={"selected_by_percent":"8","price":80,"position":4}
        self.assertGreater(_gw1_market_prior(a),_gw1_market_prior(b))
    def test_vice_prefers_attacker(self):
        rows={}
        positions=[1,1]+[2]*5+[3]*5+[4]*3
        vals=[7.0,3.0,6.0,5.5,5,4.5,4,8.0,7.5,7,5,4,7.2,6.5,5.5]
        for i,(pos,pts) in enumerate(zip(positions,vals),1):
            rows[i]={"position":pos,"per_gw":{1:pts},"confidence":"LOW","expected_minutes":90}
        lu=best_lineup(list(rows),rows,1,.2)
        self.assertIn(rows[lu["vice_captain"]]["position"],{3,4})
if __name__=="__main__": unittest.main()
