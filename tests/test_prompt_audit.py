from fpl_ai_manager.prompting import request_audit_text


def test_request_audit_contains_instructions_and_input():
    text = request_audit_text({"mode": "gw1_initial_build", "next_gameweek": 1}, "gpt-5", True)
    assert "model: gpt-5" in text
    assert "web_search" in text
    assert "--- instructions ---" in text
    assert "--- input ---" in text
    assert '"next_gameweek":1' in text
    assert "OPENAI_API_KEY" not in text
