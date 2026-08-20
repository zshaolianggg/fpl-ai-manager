
import unittest
from fpl_ai_manager.lineup import best_lineup

class LineupTests(unittest.TestCase):
    def test_legal_lineup(self):
        rows={}
        pos=[1,1]+[2]*5+[3]*5+[4]*3
        for i,p in enumerate(pos,1):
            rows[i]={"position":p,"per_gw":{2:float(i)}}
        lu=best_lineup(list(rows),rows,2,.2)
        self.assertEqual(len(lu["starters"]),11)
        self.assertIn(lu["captain"],lu["starters"])
        self.assertEqual(len(lu["bench"]),4)

if __name__=="__main__": unittest.main()
