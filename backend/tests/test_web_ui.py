def test_web_ui_is_served_at_root(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "Portfolio Exposure Graph" in response.text
    assert "Create &amp; sync portfolio" in response.text
    assert 'id="dependency-list"' in response.text


def test_web_ui_static_assets_are_served(client):
    script_response = client.get("/static/app.js")
    style_response = client.get("/static/styles.css")

    assert script_response.status_code == 200
    assert style_response.status_code == 200
    assert "/graph/dependency-paths?limit=500" in script_response.text
    assert ".dependency-card" in style_response.text
