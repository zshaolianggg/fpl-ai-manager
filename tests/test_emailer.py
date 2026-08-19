from fpl_ai_manager.emailer import _markdown_to_html


def test_markdown_to_html_renders_headings_and_lists():
    html = _markdown_to_html("# FPL GW1\n\n## Captaincy\n- **Captain:** Haaland")
    assert "<h1>FPL GW1</h1>" in html
    assert "<h2>Captaincy</h2>" in html
    assert "<strong>Captain:</strong> Haaland" in html
    assert "<li>" in html


def test_position_labels_are_promoted_to_subheadings():
    body = """## Initial squad
- **Goalkeepers**
- Raya — 5.5
- Areola — 4.5

Defenders:
- Gabriel — 6.0

**Midfielders**
- Saka — 10.0

- Forwards
- Haaland — 15.0
"""
    rendered = _markdown_to_html(body)
    assert '<h3 class="position-heading">Goalkeepers</h3>' in rendered
    assert '<h3 class="position-heading">Defenders</h3>' in rendered
    assert '<h3 class="position-heading">Midfielders</h3>' in rendered
    assert '<h3 class="position-heading">Forwards</h3>' in rendered
    assert '<li>Raya — 5.5</li>' in rendered
    assert '<li>Haaland — 15.0</li>' in rendered
    assert '<li><strong>Goalkeepers</strong></li>' not in rendered
