"""Divoom Hub was called Ditoo Spotify: data, login and autostart carry over."""

import json

from core import settings as settings_mod
from core import spotify
from timesgate import digits


def test_old_picture_paths_point_into_new_folder(tmp_path, monkeypatch):
    old, new = tmp_path / "DitooSpotify", tmp_path / "DivoomHub"
    monkeypatch.setattr(settings_mod, "LEGACY_APP_DIR", old)
    monkeypatch.setattr(settings_mod, "APP_DIR", new)
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "tg_side_media": [str(old / "timesgate" / "side_0.gif"), "", "D:\\pics\\a.png", ""],
        "tg_themes": [{"name": "Pack", "style": "custom",
                       "chars": {"1": str(old / "timesgate" / "packs" / "x" / "1.png")}}],
        "tg_themes_version": digits.THEMES_VERSION,
    }), encoding="utf-8")
    s = settings_mod.Settings.load(cfg)
    assert s.tg_side_media[0] == str(new / "timesgate" / "side_0.gif")
    assert s.tg_side_media[2] == "D:\\pics\\a.png"  # outside the data folder: untouched
    assert s.tg_themes[0]["chars"]["1"] == str(new / "timesgate" / "packs" / "x" / "1.png")


def test_spotify_login_moves_to_new_keyring_name(monkeypatch):
    store = {(spotify.LEGACY_KEYRING_SERVICE, spotify.KEYRING_USER): "RT"}
    monkeypatch.setattr(spotify.keyring, "get_password", lambda s, u: store.get((s, u)))
    monkeypatch.setattr(spotify.keyring, "set_password", lambda s, u, p: store.__setitem__((s, u), p))
    monkeypatch.setattr(spotify.keyring, "delete_password", lambda s, u: store.pop((s, u)))
    assert spotify.SpotifyAuth.has_saved_login()
    assert store == {(spotify.KEYRING_SERVICE, spotify.KEYRING_USER): "RT"}


def test_follow_light_hides_replaced_colours():
    for style in digits.FOLLOW_LIGHT_STYLES:
        theme = {"style": style}
        everything = [r[0] for r in digits.editable_roles(theme)]
        following = [r[0] for r in digits.editable_roles(theme | {"follow_light": True})]
        hidden = set(everything) - set(following)
        assert hidden and hidden <= digits.LIGHT_ROLES[style]
    assert [r[0] for r in digits.editable_roles({"style": "custom"})] == ["bg"]
