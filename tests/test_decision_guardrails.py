
import unittest
from fpl_ai_manager.lineup import best_lineup

class DecisionGuardrailTests(unittest.TestCase):
    def _row(self,pos,pts,conf="LOW",mins=90):
        return {"position":pos,"per_gw":{1:pts},"confidence":conf,"expected_minutes":mins}

    def test_low_confidence_gk_does_not_captain_small_edge(self):
        p={
          1:self._row(1,8.0,"LOW"),
          2:self._row(1,3.0),
          3:self._row(2,5.0),4:self._row(2,4.5),5:self._row(2,4.0),6:self._row(2,3.5),7:self._row(2,3.0),
          8:self._row(3,6.5),9:self._row(3,6.0),10:self._row(3,5.5),11:self._row(3,4.0),12:self._row(3,3.0),
          13:self._row(4,6.0),14:self._row(4,5.0),15:self._row(4,4.0)
        }
        lu=best_lineup(list(p),p,1,.2)
        self.assertIn(p[lu["captain"]]["position"],{3,4})

    def test_defender_can_captain_only_with_big_edge(self):
        p={
          1:self._row(1,4.0,"HIGH"),
          2:self._row(1,3.0),
          3:self._row(2,10.0,"HIGH"),4:self._row(2,4.5),5:self._row(2,4.0),6:self._row(2,3.5),7:self._row(2,3.0),
          8:self._row(3,6.0,"HIGH"),9:self._row(3,5.8),10:self._row(3,5.5),11:self._row(3,4.0),12:self._row(3,3.0),
          13:self._row(4,5.5),14:self._row(4,5.0),15:self._row(4,4.0)
        }
        lu=best_lineup(list(p),p,1,.2)
        self.assertEqual(lu["captain"],3)

if __name__=="__main__":
    unittest.main()
