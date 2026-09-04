import unittest
from datetime import datetime

from fpl_ai_manager.team_model import build_team_strengths, match_understat_teams
from fpl_ai_manager.set_pieces import infer_set_piece_role, penalty_goals_current_season
from fpl_ai_manager.projections import attacking_rates
from fpl_ai_manager.captaincy import correlation_discount
from fpl_ai_manager.lineup import production_captain_audit


def _fpl_team_rows(names):
    return [{
        "id": i, "name": name,
        "strength_attack_home": 1000, "strength_attack_away": 1000,
        "strength_defence_home": 1000, "strength_defence_away": 1000,
    } for i, name in enumerate(names, 1)]


def _understat_team(uid, title, home_xg, home_xga, away_xg, away_xga, date="2026-08-20 15:00:00"):
    return {
        "id": uid, "title": title,
        "history": [
            {"h_a": "h", "xG": home_xg, "xGA": home_xga, "date": date},
            {"h_a": "a", "xG": away_xg, "xGA": away_xga, "date": date},
        ],
    }


TEAM_NAMES = [
    "Arsenal", "Chelsea", "Liverpool", "Everton", "Fulham",
    "Brentford", "Bournemouth", "Burnley", "Sunderland", "Wolves",
]


class TeamStrengthBlendingTests(unittest.TestCase):
    def test_understat_data_shifts_ratings_relative_to_neutral_fpl_labels(self):
        rows = _fpl_team_rows(TEAM_NAMES)
        understat = {
            str(i): (_understat_team(str(i), TEAM_NAMES[i-1], 3.0, 0.5, 1.0, 1.2) if i == 1
                     else _understat_team(str(i), TEAM_NAMES[i-1], 1.0, 1.4, 1.0, 1.4))
            for i in range(1, 11)
        }
        strengths = build_team_strengths(
            rows, understat, {}, now=datetime(2026, 9, 1), prior_pseudo_weight=1.0,
        )
        self.assertGreater(strengths[1].attack_home, strengths[2].attack_home)
        self.assertGreater(strengths[1].attack_home, 1.0)
        self.assertGreater(strengths[1].defence_home, strengths[2].defence_home)

    def test_without_understat_data_matches_pure_fpl_labels(self):
        rows = _fpl_team_rows(TEAM_NAMES)
        plain = build_team_strengths(rows)
        blended = build_team_strengths(rows, None, None)
        self.assertEqual(plain, blended)

    def test_too_few_matched_teams_falls_back_to_fpl_labels(self):
        rows = _fpl_team_rows(TEAM_NAMES)
        plain = build_team_strengths(rows)
        understat = {"1": _understat_team("1", TEAM_NAMES[0], 2.5, 0.4, 2.0, 0.6)}
        blended = build_team_strengths(rows, understat, {}, now=datetime(2026, 9, 1))
        self.assertEqual(plain, blended)

    def test_name_matching_tolerates_common_fpl_understat_variants(self):
        rows = [
            {"id": 1, "name": "Tottenham Hotspur"},
            {"id": 2, "name": "AFC Bournemouth"},
            {"id": 3, "name": "West Ham United"},
        ]
        understat = {
            "10": {"title": "Tottenham"},
            "20": {"title": "Bournemouth"},
            "30": {"title": "West Ham"},
        }
        matched = match_understat_teams(rows, understat)
        self.assertEqual(matched, {"10": 1, "20": 2, "30": 3})


class PenaltySignalTests(unittest.TestCase):
    def test_penalty_goals_from_understat_goal_split(self):
        player = {"web_name": "Taker"}
        understat_current = {"taker": {"goals": "5", "npg": "3"}}
        self.assertEqual(penalty_goals_current_season(player, understat_current), 2.0)

    def test_dominant_scorer_is_flagged_as_confirmed_taker(self):
        player = {"web_name": "Taker", "team": 1}
        understat_current = {"taker": {"goals": "5", "npg": "3"}}
        role = infer_set_piece_role(player, understat_current, {1: 2.0})
        self.assertTrue(role.is_penalty_taker)
        self.assertAlmostEqual(role.penalty_share, 1.0)

    def test_non_taker_teammate_is_not_flagged(self):
        player = {"web_name": "NonTaker", "team": 1}
        understat_current = {"nontaker": {"goals": "4", "npg": "4"}}
        role = infer_set_piece_role(player, understat_current, {1: 2.0})
        self.assertFalse(role.is_penalty_taker)
        self.assertEqual(role.penalty_share, 0.0)

    def test_confirmed_penalty_taker_gets_higher_confidence_on_thin_minutes(self):
        player = {"web_name": "Test Taker", "element_type": 4, "minutes": "90",
                  "expected_goals": "0.9", "expected_assists": "0.05"}
        _, _, conf_unconfirmed = attacking_rates(player, {}, {}, penalty_confirmed=False)
        _, _, conf_confirmed = attacking_rates(player, {}, {}, penalty_confirmed=True)
        self.assertEqual(conf_unconfirmed, "LOW")
        self.assertEqual(conf_confirmed, "MEDIUM")


def _cap_row(pid, pos, pts, team_id, opponent, gw=5):
    return {
        "player_id": pid, "position": pos, "price": 80, "expected_minutes": 82, "confidence": "HIGH",
        "team_id": team_id, "selected_by_percent": "10",
        "per_gw": {gw: pts}, "fixtures": [{"gw": gw, "opponent": opponent}],
        "minutes_projection": {"p_appearance": .95},
    }


class CaptaincyCorrelationTests(unittest.TestCase):
    def test_same_team_and_opponent_vice_are_discounted_independent_is_not(self):
        cap = {"team_id": 1, "fixtures": [{"gw": 5, "opponent": 2}]}
        self.assertGreater(correlation_discount(cap, {"team_id": 1}, 5), 0.0)
        self.assertGreater(correlation_discount(cap, {"team_id": 2}, 5), 0.0)
        self.assertEqual(correlation_discount(cap, {"team_id": 3}, 5), 0.0)

    def test_production_vice_prefers_independent_hedge_within_margin(self):
        proj = {
            1: _cap_row(1, 4, 10.0, team_id=1, opponent=2),
            2: _cap_row(2, 3, 6.0, team_id=1, opponent=2),
            3: _cap_row(3, 3, 5.3, team_id=3, opponent=9),
        }
        audit = production_captain_audit([1, 2, 3], proj, 5)
        self.assertEqual(audit["captain"], 1)
        self.assertEqual(audit["vice_captain"], 3)
        self.assertEqual(audit["vice_correlation_discount"], 0.0)

    def test_production_vice_keeps_same_team_pick_when_hedge_costs_too_much(self):
        proj = {
            1: _cap_row(1, 4, 10.0, team_id=1, opponent=2),
            2: _cap_row(2, 3, 6.0, team_id=1, opponent=2),
            3: _cap_row(3, 3, 3.0, team_id=3, opponent=9),
        }
        audit = production_captain_audit([1, 2, 3], proj, 5)
        self.assertEqual(audit["vice_captain"], 2)


if __name__ == "__main__":
    unittest.main()
