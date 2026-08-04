from fastapi.testclient import TestClient

from mesa_legal_data.web.app import create_app


def test_web_admin_html_smoke():
    app = create_app()
    client = TestClient(app)

    # 1. GET /
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert "MESA Legal Data" in html
    assert "/static/styles.css" in html
    assert "/static/app.js" in html

    # 2. GET /static/styles.css
    css_res = client.get("/static/styles.css")
    assert css_res.status_code == 200
    assert ":root" in css_res.text

    # 3. GET /static/app.js
    js_res = client.get("/static/app.js")
    assert js_res.status_code == 200
    assert "switchView" in js_res.text
