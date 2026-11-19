"""Spotify Web API: OAuth Authorization Code + PKCE (no client secret) and
the currently-playing endpoint.

Spotify rules this follows (2025-2026):
  * redirect URI must use the loopback IP, not "localhost": REDIRECT_URI below
    must be added verbatim in the app's settings on developer.spotify.com;
  * PKCE needs only the Client ID;
  * only the two read scopes from the spec are requested.

The refresh token lives in Windows Credential Manager (keyring), never in
config.json or the log.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import logging
import secrets
import threading
import time
import urllib.parse
import webbrowser

import keyring
import requests

from .models import TrackInfo

log = logging.getLogger(__name__)

REDIRECT_HOST = "127.0.0.1"
REDIRECT_PORT = 8888
REDIRECT_URI = f"http://{REDIRECT_HOST}:{REDIRECT_PORT}/callback"
SCOPES = "user-read-currently-playing user-read-playback-state"
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"

from core.profile import PROFILE_NAME, TEST_MODE

KEYRING_SERVICE = PROFILE_NAME
LEGACY_KEYRING_SERVICE = "DitooSpotify" if PROFILE_NAME == "DivoomHub" else PROFILE_NAME
KEYRING_USER = "spotify_refresh_token"


def saved_refresh_token() -> str | None:
    """The stored refresh token; one saved under the old app name is moved over."""
    token = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    if token or TEST_MODE:
        return token
    token = keyring.get_password(LEGACY_KEYRING_SERVICE, KEYRING_USER)
    if token:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, token)
        try:
            keyring.delete_password(LEGACY_KEYRING_SERVICE, KEYRING_USER)
        except keyring.errors.PasswordDeleteError:
            pass
    return token


class SpotifyError(Exception):
    pass


class SpotifyAuthError(SpotifyError):
    """Credentials are missing, revoked or invalid: the user must log in again."""


class SpotifyRateLimited(SpotifyError):
    def __init__(self, retry_after: float):
        super().__init__(f"rate limited, retry after {retry_after:.0f}s")
        self.retry_after = retry_after


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    return verifier, pkce_challenge(verifier)


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    result: dict[str, str] = {}

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        url = urllib.parse.urlparse(self.path)
        if url.path != "/callback":
            self.send_error(404)
            return
        params = dict(urllib.parse.parse_qsl(url.query))
        type(self).result = params
        ok = "code" in params
        body = ("<h2>Divoom Hub: готово, вкладку можно закрыть.</h2>" if ok else
                f"<h2>Divoom Hub: ошибка авторизации ({params.get('error', '?')}).</h2>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, *args) -> None:  # keep the code out of the log
        pass


class SpotifyAuth:
    def __init__(self, client_id: str, session: requests.Session | None = None):
        if not client_id:
            raise SpotifyAuthError("Spotify Client ID is not set")
        self.client_id = client_id
        self.http = session or requests.Session()
        self._access_token: str | None = None
        self._expires_at = 0.0
        self._lock = threading.Lock()

    # -- stored refresh token ---------------------------------------------

    @staticmethod
    def has_saved_login() -> bool:
        return bool(saved_refresh_token())

    @staticmethod
    def logout() -> None:
        for service in dict.fromkeys((KEYRING_SERVICE, LEGACY_KEYRING_SERVICE)):
            try:
                keyring.delete_password(service, KEYRING_USER)
            except keyring.errors.PasswordDeleteError:
                pass

    # -- interactive login -------------------------------------------------

    def login(self, timeout: float = 300) -> None:
        """Open the browser, wait for the redirect, store the refresh token."""
        verifier, challenge = pkce_pair()
        state = secrets.token_urlsafe(16)
        _CallbackHandler.result = {}
        try:
            server = http.server.HTTPServer((REDIRECT_HOST, REDIRECT_PORT), _CallbackHandler)
        except OSError as e:
            raise SpotifyError(f"Port {REDIRECT_PORT} is busy, close the program using it: {e}") from e
        server.timeout = 1
        url = AUTH_URL + "?" + urllib.parse.urlencode({
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
            "state": state,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
        })
        log.info("Opening browser for Spotify login")
        webbrowser.open(url)
        deadline = time.monotonic() + timeout
        try:
            while not _CallbackHandler.result and time.monotonic() < deadline:
                server.handle_request()
        finally:
            server.server_close()

        params = _CallbackHandler.result
        if not params:
            raise SpotifyAuthError("Login timed out")
        if params.get("state") != state:
            raise SpotifyAuthError("Login failed: state mismatch")
        if "code" not in params:
            raise SpotifyAuthError(f"Login refused: {params.get('error', 'unknown error')}")
        self._token_request({
            "grant_type": "authorization_code",
            "code": params["code"],
            "redirect_uri": REDIRECT_URI,
            "client_id": self.client_id,
            "code_verifier": verifier,
        })
        log.info("Spotify login successful")

    # -- tokens ------------------------------------------------------------

    def access_token(self) -> str:
        with self._lock:
            if self._access_token and time.time() < self._expires_at - 60:
                return self._access_token
            refresh = saved_refresh_token()
            if not refresh:
                raise SpotifyAuthError("Not logged in to Spotify")
            self._token_request({
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": self.client_id,
            })
            assert self._access_token
            return self._access_token

    def invalidate(self) -> None:
        with self._lock:
            self._access_token = None

    def _token_request(self, data: dict[str, str]) -> None:
        try:
            r = self.http.post(TOKEN_URL, data=data, timeout=10)
        except requests.RequestException as e:
            raise SpotifyError(f"Token request failed: {e}") from e
        if r.status_code in (400, 401):
            # invalid_grant = revoked/expired refresh token, invalid_client = wrong Client ID
            try:
                error = r.json().get("error", r.status_code)
            except ValueError:
                error = r.status_code
            log.warning("Spotify token rejected: %s", error)
            if data["grant_type"] == "refresh_token":
                self.logout()
            raise SpotifyAuthError(f"Spotify rejected the credentials ({error})")
        if not r.ok:
            raise SpotifyError(f"Token endpoint returned HTTP {r.status_code}")
        body = r.json()
        self._access_token = body["access_token"]
        self._expires_at = time.time() + float(body.get("expires_in", 3600))
        if body.get("refresh_token"):  # Spotify may rotate it
            keyring.set_password(KEYRING_SERVICE, KEYRING_USER, body["refresh_token"])


def parse_currently_playing(body: dict) -> TrackInfo | None:
    item = body.get("item")
    if not item:
        return None  # ads, or playback the API cannot describe
    if item.get("type") == "episode":
        images = item.get("images") or []
        artist = (item.get("show") or {}).get("name", "")
        album = artist
    else:
        album_obj = item.get("album") or {}
        images = album_obj.get("images") or []
        artist = ", ".join(a.get("name", "") for a in item.get("artists") or [])
        album = album_obj.get("name", "")
    # Images come largest first (640, 300, 64). 300 px is plenty for a 16x16
    # panel and the colour analysis, and it is ~10x smaller to download than 640.
    sized = sorted((i for i in images if i.get("url")), key=lambda i: i.get("width") or 0)
    art = next((i["url"] for i in sized if (i.get("width") or 0) >= 200),
               sized[-1]["url"] if sized else None)
    return TrackInfo(
        is_playing=bool(body.get("is_playing")),
        track_id=item.get("id") or item.get("uri", ""),  # local files have no id
        track_name=item.get("name", ""),
        artist_name=artist,
        album_name=album,
        album_art_url=art,
        progress_ms=int(body.get("progress_ms") or 0),
        duration_ms=int(item.get("duration_ms") or 0),
    )


class SpotifyClient:
    def __init__(self, auth: SpotifyAuth):
        self.auth = auth

    def get_current_track(self) -> TrackInfo | None:
        """Current playback, or None when nothing is playing on any device."""
        for attempt in (1, 2):
            headers = {"Authorization": f"Bearer {self.auth.access_token()}"}
            try:
                r = self.auth.http.get(f"{API}/me/player/currently-playing",
                                       params={"additional_types": "episode"},
                                       headers=headers, timeout=10)
            except requests.RequestException as e:
                raise SpotifyError(f"Spotify unreachable: {e}") from e
            if r.status_code == 401 and attempt == 1:
                self.auth.invalidate()  # token expired early: refresh once
                continue
            break
        if r.status_code == 204 or not r.content:
            return None
        if r.status_code == 429:
            raise SpotifyRateLimited(float(r.headers.get("Retry-After", 5)))
        if r.status_code in (401, 403):
            # 403 in Development Mode usually means the account is not listed in
            # the app's "User Management" on developer.spotify.com.
            raise SpotifyAuthError(f"Spotify API refused access (HTTP {r.status_code})")
        if not r.ok:
            raise SpotifyError(f"Spotify API returned HTTP {r.status_code}")
        return parse_currently_playing(r.json())
