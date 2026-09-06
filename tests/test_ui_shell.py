"""Public UI aliases keep machine endpoints backward compatible."""

import pytest
from fastapi.testclient import TestClient

from tradearena.api.main import app


@pytest.mark.parametrize("path", ["/", "/arena", "/leaderboard-live", "/traders/example"])
def test_shared_shell(path):
    response = TestClient(app).get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text.count('class="ui-header"') == 1
    assert response.text.count('class="ui-footer"') == 1
    assert 'href="#main-content"' in response.text
    assert "<!-- app-header -->" not in response.text
    assert 'href="/leaderboard-live"' in response.text


def test_profile_and_developer_aliases():
    client = TestClient(app)
    assert client.get("/traders/example").text == client.get("/profile/example").text
    assert client.get("/developers").content == client.get("/developer-guide").content
    assert client.get("/ui/components.js").status_code == 200


def test_shell_escapes_no_dynamic_navigation():
    # API routes remain registered as JSON, rather than content negotiation.
    route = next(r for r in app.routes if getattr(r, "path", None) == "/leaderboard")
    assert route.response_model.__name__ == "LeaderboardResponse"
