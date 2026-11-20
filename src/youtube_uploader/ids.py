"""Parsing of YouTube video and playlist identifiers from IDs or URLs."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
PLAYLIST_ID_RE = re.compile(r"^(PL|UU|FL|LL|OL|RD)[A-Za-z0-9_-]{10,}$")


def parse_video_id(value: str) -> str:
    """Accept a bare video ID or any common YouTube URL form and return the ID."""
    value = value.strip()
    if VIDEO_ID_RE.match(value):
        return value

    url = urlparse(value if "://" in value else f"https://{value}")
    host = (url.hostname or "").removeprefix("www.").removeprefix("m.")
    candidate: str | None = None
    if host == "youtu.be":
        candidate = url.path.lstrip("/").split("/")[0]
    elif host in {"youtube.com", "music.youtube.com", "studio.youtube.com"}:
        if url.path == "/watch":
            candidate = parse_qs(url.query).get("v", [None])[0]
        else:
            parts = [p for p in url.path.split("/") if p]
            # /shorts/ID, /embed/ID, /live/ID, /v/ID, studio: /video/ID/edit
            if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live", "v", "video"}:
                candidate = parts[1]

    if candidate and VIDEO_ID_RE.match(candidate):
        return candidate
    raise ValueError(f"not a YouTube video ID or URL: {value!r}")


def parse_playlist_ref(value: str) -> tuple[str, bool]:
    """Return (value, is_id). A playlist URL or ID gives an ID; anything else is a title."""
    value = value.strip()
    if "list=" in value:
        url = urlparse(value if "://" in value else f"https://{value}")
        list_id = parse_qs(url.query).get("list", [None])[0]
        if list_id:
            return list_id, True
    if PLAYLIST_ID_RE.match(value):
        return value, True
    return value, False
