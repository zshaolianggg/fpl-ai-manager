
import unittest
from fpl_ai_manager.confidence import recommendation_confidence
from fpl_ai_manager.chips import chip_thresholds

class PolicyTests(unittest.TestCase):
    def test_chip_threshold_tapers(self):
        cfg={"chips":{"free_hit_early_threshold":18,"free_hit_late_threshold":12,
                      "wildcard_early_threshold":25,"wildcard_late_threshold":20,
                      "bench_boost_early_threshold":16,"bench_boost_late_threshold":12,
                      "triple_captain_normal_points_target":10}}
        self.assertGreater(chip_thresholds(cfg,2)["freehit"],chip_thresholds(cfg,18)["freehit"])
    def test_confidence_not_fake_precision(self):
        p={i:{"confidence":"MEDIUM"} for i in range(1,12)}
        chosen={"lineup":{"starters":list(range(1,12))}}
        self.assertIn(recommendation_confidence({"actionable":True},chosen,p,[],[],3),{"HIGH","MEDIUM","LOW"})
if __name__=="__main__":unittest.main()
