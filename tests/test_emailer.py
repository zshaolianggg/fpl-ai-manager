from fpl_ai_manager.emailer import _markdown_to_html


def test_markdown_to_html_renders_headings_and_lists():
    html = _markdown_to_html("# FPL GW1\n\n## Captaincy\n- **Captain:** Haaland")
    assert "<h1>FPL GW1</h1>" in html
    assert "<h2>Captaincy</h2>" in html
    assert "<strong>Captain:</strong> Haaland" in html
    assert "<li>" in html
