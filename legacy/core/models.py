from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TrackInfo:
    is_playing: bool
    track_id: str
    track_name: str
    artist_name: str
    album_name: str
    album_art_url: str | None
    progress_ms: int
    duration_ms: int
