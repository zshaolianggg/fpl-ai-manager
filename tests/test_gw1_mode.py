from fpl_ai_manager.prompting import SYSTEM


def test_gw1_prompt_contains_legality_constraints():
    assert 'exactly 2 GK, 5 DEF, 5 MID, 3 FWD' in SYSTEM
    assert 'maximum 3 players from any one Premier League club' in SYSTEM
    assert '£100.0m' in SYSTEM
    assert 'Every selected player MUST appear in candidate_pool' in SYSTEM
