"""End-to-end PKCE login with the browser and Spotify replaced by fakes."""

import threading
import urllib.parse
import urllib.request

import pytest

from core import spotify


class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.ok, self.content, self.headers = status < 400, b"x", {}

    def json(self):
        return self._body


class FakeSession:
    def __init__(self):
        self.posts = []

    def post(self, url, data, timeout):
        self.posts.append(data)
        return FakeResponse(200, {"access_token": "AT", "expires_in": 3600, "refresh_token": "RT"})


@pytest.fixture
def vault(monkeypatch):
    store = {}
    monkeypatch.setattr(spotify.keyring, "set_password", lambda s, u, p: store.__setitem__(u, p))
    monkeypatch.setattr(spotify.keyring, "get_password", lambda s, u: store.get(u))
    return store


def test_login_flow(monkeypatch, vault):
    def fake_browser(url):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        assert q["redirect_uri"] == spotify.REDIRECT_URI
        assert q["code_challenge_method"] == "S256"
        assert q["scope"] == "user-read-currently-playing user-read-playback-state"
        callback = f"{spotify.REDIRECT_URI}?code=CODE&state={q['state']}"
        threading.Thread(target=lambda: urllib.request.urlopen(callback, timeout=5).read()).start()

    monkeypatch.setattr(spotify.webbrowser, "open", fake_browser)
    session = FakeSession()
    auth = spotify.SpotifyAuth("CLIENT", session)
    auth.login(timeout=10)

    sent = session.posts[0]
    assert sent["grant_type"] == "authorization_code" and sent["code"] == "CODE"
    assert sent["client_id"] == "CLIENT" and "client_secret" not in sent
    assert spotify.pkce_challenge(sent["code_verifier"])  # verifier was sent
    assert vault[spotify.KEYRING_USER] == "RT"
    assert auth.access_token() == "AT"


def test_login_rejects_wrong_state(monkeypatch, vault):
    def fake_browser(url):
        callback = f"{spotify.REDIRECT_URI}?code=CODE&state=forged"
        threading.Thread(target=lambda: urllib.request.urlopen(callback, timeout=5).read()).start()

    monkeypatch.setattr(spotify.webbrowser, "open", fake_browser)
    with pytest.raises(spotify.SpotifyAuthError, match="state"):
        spotify.SpotifyAuth("CLIENT", FakeSession()).login(timeout=10)
    assert spotify.KEYRING_USER not in vault
