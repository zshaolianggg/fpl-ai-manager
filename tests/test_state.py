from fpl_ai_manager.state import build_state_check, resolve_manual_squad_ids, validate_squad


def test_manual_names_resolve_case_insensitive():
    players = [
        {"id": 1, "web_name": "Saka", "first_name": "Bukayo", "second_name": "Saka"},
        {"id": 2, "web_name": "Haaland", "first_name": "Erling", "second_name": "Haaland"},
    ]
    ids, warnings = resolve_manual_squad_ids({"squad_player_names": ["saka", "Erling Haaland"]}, players)
    assert ids == [1, 2]
    assert warnings == []


def test_validate_squad_flags_wrong_size():
    players = {i: {"id": i} for i in range(1, 16)}
    warnings = validate_squad(list(range(1, 15)), players)
    assert any("expected 15" in w for w in warnings)


def test_state_check_explains_pre_gw1_public_limit():
    check = build_state_check(
        squad_ids=[], squad_source="none", bank=None, bank_source="none",
        free_transfers=None, chip_history=[], chips_override=None,
        latest_public_gameweek=None, warnings=[]
    )
    assert check.squad_status == "unavailable"
    assert any("first season deadline" in note for note in check.notes)
