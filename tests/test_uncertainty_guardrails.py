
import unittest
from fpl_ai_manager.lineup import best_lineup
from fpl_ai_manager.optimizer import robustness_tiebreak

class UncertaintyGuardrailTests(unittest.TestCase):
    def _r(self,pos,pts,price=60,own="5",conf="LOW",mins=90):
        return {"position":pos,"per_gw":{1:pts,2:pts,3:pts,4:pts,5:pts,6:pts},
                "confidence":conf,"expected_minutes":mins,"price":price,
                "selected_by_percent":own}

    def test_low_conf_prefers_high_owned_premium_captain_on_thin_edge(self):
        p={
          1:self._r(1,4),2:self._r(1,3),
          3:self._r(2,5),4:self._r(2,4.5),5:self._r(2,4),6:self._r(2,3.5),7:self._r(2,3),
          8:self._r(3,8.4,120,"20"),9:self._r(3,6),10:self._r(3,5.5),11:self._r(3,5),12:self._r(3,4),
          13:self._r(4,8.0,155,"75"),14:self._r(4,5),15:self._r(4,4.5)
        }
        lu=best_lineup(list(p),p,1,.2)
        self.assertEqual(lu["captain"],13)

    def test_robustness_tiebreak_penalizes_expensive_bench(self):
        p={i:self._r(3 if i>7 else (1 if i<3 else 2),5,75 if i==15 else 50) for i in range(1,16)}
        plan={"squad_ids":list(p),"lineup":{"bench":[15,2,3,4],"captain":8}}
        self.assertLess(robustness_tiebreak(plan,p),1.0)

if __name__=="__main__":
    unittest.main()
