from core.spotify import REDIRECT_URI, parse_currently_playing, pkce_challenge


def test_pkce_challenge_rfc7636_vector():
    # RFC 7636 appendix B
    assert pkce_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == \
        "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_redirect_uri_uses_loopback_ip():
    # Spotify rejects "localhost" redirect URIs since 2025.
    assert REDIRECT_URI == "http://127.0.0.1:8888/callback"


def images():
    return [{"url": "big", "width": 640}, {"url": "mid", "width": 300}, {"url": "small", "width": 64}]


def test_parse_track():
    body = {
        "is_playing": True,
        "progress_ms": 1234,
        "item": {
            "type": "track", "id": "abc", "name": "Song", "duration_ms": 200000,
            "artists": [{"name": "A"}, {"name": "B"}],
            "album": {"name": "Album", "images": images()},
        },
    }
    t = parse_currently_playing(body)
    assert (t.track_id, t.track_name, t.artist_name, t.album_name) == ("abc", "Song", "A, B", "Album")
    assert t.album_art_url == "mid"
    assert t.is_playing and t.progress_ms == 1234 and t.duration_ms == 200000


def test_parse_episode_and_local_file():
    ep = parse_currently_playing({"is_playing": False, "item": {
        "type": "episode", "id": "ep1", "name": "Ep", "images": images(), "show": {"name": "Show"}}})
    assert (ep.artist_name, ep.album_art_url, ep.is_playing) == ("Show", "mid", False)

    local = parse_currently_playing({"item": {
        "type": "track", "id": None, "uri": "spotify:local:x", "name": "L",
        "artists": [], "album": {"name": "", "images": []}}})
    assert local.track_id == "spotify:local:x" and local.album_art_url is None


def test_parse_nothing():
    assert parse_currently_playing({"is_playing": True, "item": None}) is None
