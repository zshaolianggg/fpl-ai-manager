import unittest
from fpl_ai_manager.rules import rules_for_season, season_start_year
from fpl_ai_manager.team_model import build_team_strengths, fixture_expectation
from fpl_ai_manager.minutes import project_minutes
from fpl_ai_manager.projections import (
    defensive_action_rate90,
    expected_defensive_contribution_points,
    project_fixture,
)


class V3ProjectionEngineTests(unittest.TestCase):
    def test_2026_27_goal_scoring_rules(self):
        rules = rules_for_season("2026/27")
        self.assertEqual(rules.goal_points[1], 10)
        self.assertEqual(rules.goal_points[2], 6)
        self.assertEqual(rules.defensive_contribution_thresholds[2], 10)
        self.assertNotIn(1, rules.defensive_contribution_thresholds)
        self.assertEqual(season_start_year("2026/27"), 2026)

    def test_team_strength_changes_fixture_clean_sheet_probability(self):
        rows = [
            {"id":1,"strength_attack_home":1400,"strength_attack_away":1300,"strength_defence_home":1500,"strength_defence_away":1450},
            {"id":2,"strength_attack_home":900,"strength_attack_away":850,"strength_defence_home":900,"strength_defence_away":850},
        ]
        s = build_team_strengths(rows)
        strong_home = fixture_expectation(1,2,s)
        weak_home = fixture_expectation(2,1,s)
        self.assertGreater(strong_home.home_xg, weak_home.home_xg)
        self.assertGreater(strong_home.home_cs_probability, weak_home.home_cs_probability)

    def test_congestion_reduces_start_probability_not_all_future_minutes(self):
        player={"web_name":"Test","element_type":3,"status":"a"}
        history=[{"minutes":90},{"minutes":90},{"minutes":88},{"minutes":86}]
        normal=project_minutes(player,history,None,{},congestion_days=7)
        congested=project_minutes(player,history,None,{},congestion_days=3)
        self.assertLess(congested.p_start, normal.p_start)
        self.assertLess(congested.expected_minutes, normal.expected_minutes)
        self.assertGreater(normal.expected_minutes, 70)

    def test_defensive_contribution_projection_rewards_high_action_defender(self):
        rules=rules_for_season("2026/27")
        player={"web_name":"CB","element_type":2,"status":"a"}
        history=[
            {"minutes":90,"clearances_blocks_interceptions":8,"tackles":4},
            {"minutes":90,"clearances_blocks_interceptions":9,"tackles":3},
            {"minutes":90,"clearances_blocks_interceptions":7,"tackles":4},
        ]
        mp=project_minutes(player,history,None,{})
        self.assertGreater(defensive_action_rate90(history,2),10)
        pts=expected_defensive_contribution_points(history,2,mp,rules)
        self.assertGreater(pts,0.8)

    def test_goalkeeper_goal_uses_ten_points(self):
        rules=rules_for_season("2026/27")
        player={"element_type":1,"minutes":900,"saves":30,"bonus":0}
        fixture={"venue":"H","home_team":1,"away_team":2,"difficulty":3}
        fp=project_fixture(player,90,1.0,0.0,fixture,history=[],scoring_rules=rules)
        # Matchup shrinkage may alter the 1.0 xG rate, but a GK goal component
        # must still be materially above the old six-point scoring path.
        self.assertGreater(fp.goal_points,6.0)


if __name__ == "__main__":
    unittest.main()
