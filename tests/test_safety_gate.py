from fpl_ai_manager.state import build_state_check, safety_warning_markdown


def test_actionable_requires_verified_squad_and_bank():
    ok = build_state_check(
        squad_ids=list(range(1, 16)), squad_source="public_locked_gw_1", bank=5,
        bank_source="public_history_gw_1", free_transfers=None, chip_history=[],
        chips_override=None, latest_public_gameweek=1, warnings=[]
    )
    assert ok.actionable is True

    no_bank = build_state_check(
        squad_ids=list(range(1, 16)), squad_source="public_locked_gw_1", bank=None,
        bank_source="none", free_transfers=None, chip_history=[], chips_override=None,
        latest_public_gameweek=1, warnings=[]
    )
    assert no_bank.actionable is False

    no_squad = build_state_check(
        squad_ids=[], squad_source="none", bank=5, bank_source="public_history_gw_1",
        free_transfers=None, chip_history=[], chips_override=None,
        latest_public_gameweek=1, warnings=[]
    )
    assert no_squad.actionable is False


def test_warning_contains_no_actionable_fpl_advice():
    snapshot = {
        "next_gameweek": 2,
        "report_type": "final",
        "state_check": {
            "squad_status": "unavailable", "squad_count": 0, "squad_source": "none",
            "bank_status": "verified", "bank_source": "public_history_gw_1",
            "latest_public_gameweek": 1, "notes": ["test diagnostic"]
        }
    }
    text = safety_warning_markdown(snapshot)
    assert "Action Withheld" in text
    assert "did **not** generate transfer" in text
    assert "test diagnostic" in text
