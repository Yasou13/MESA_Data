from pathlib import Path

from fastapi.testclient import TestClient

from mesa_legal_data.web.app import create_app

app = create_app()
client = TestClient(app)

STATIC_DIR = Path(__file__).parent.parent.parent / "src" / "mesa_legal_data" / "web" / "static"


def test_index_html_semantics_and_theme():
    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    # HTML semantics
    assert '<html lang="tr"' in html
    assert 'class="skip-link"' in html
    assert 'href="#main-content"' in html
    assert 'id="main-content"' in html
    assert 'tabindex="-1"' in html
    assert 'aria-label="Ana navigasyon"' in html

    # Theme scripts & tokens
    assert "mesa_theme" in html
    assert '<meta name="theme-color"' in html
    assert 'id="sel-theme-control"' in html

    # ARIA modals
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html

    # SVG icons used, no emoji nav
    assert "<svg" in html
    for emoji in ["📊", "➕", "📄", "🔎", "🔍", "⚠️", "🌐", "📦", "📤", "🔄", "📋", "⚙️"]:
        assert emoji not in html, f"Emoji {emoji} found in index.html navigation"


def test_css_tokens_and_dark_theme():
    response = client.get("/static/styles.css")
    assert response.status_code == 200
    css = response.text

    # Light & dark theme tokens
    assert 'html[data-theme="dark"]' in css
    assert "--color-bg: #080a0f" in css or "#080a0f" in css
    assert "--color-surface" in css
    assert ":focus-visible" in css
    assert "prefers-reduced-motion" in css


def test_static_js_files_exist_and_served():
    for js_file in ["app.js", "theme.js", "ui.js"]:
        response = client.get(f"/static/{js_file}")
        assert response.status_code == 200, f"Failed to fetch /static/{js_file}"
        assert len(response.text) > 50
