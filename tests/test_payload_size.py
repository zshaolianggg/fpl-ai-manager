import json

from fpl_ai_manager.analyzer import compact_entry, shortlist_candidates


def fake_player(i: int, pos: int):
    return {
        "id": i,
        "web_name": f"P{i}",
        "element_type": pos,
        "now_cost": 50 + i % 100,
        "total_points": i % 200,
        "form": str((i % 90) / 10),
        "points_per_game": str((i % 70) / 10),
        "selected_by_percent": str(i % 60),
        "minutes": i * 5,
        "starts": i % 38,
        "expected_goal_involvements": str((i % 50) / 10),
        "status": "a",
        "chance_of_playing_next_round": None,
        "news": "",
        "team": (i % 20) + 1,
    }


def test_candidate_shortlist_is_bounded():
    players = []
    i = 1
    for pos in range(1, 5):
        for _ in range(180):
            players.append(fake_player(i, pos))
            i += 1
    teams = {i: f"Team {i}" for i in range(1, 21)}
    result = shortlist_candidates(players, teams)
    assert len(result) == 18 + 40 + 45 + 30
    # Sanity check that the compact pool itself stays small.
    assert len(json.dumps(result)) < 150_000


def test_compact_entry_excludes_leagues():
    entry = {"id": 1, "name": "X", "summary_overall_rank": 99, "leagues": {"classic": list(range(1000))}}
    result = compact_entry(entry)
    assert result["id"] == 1
    assert "leagues" not in result
