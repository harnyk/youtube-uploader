"""Thin wrappers over YouTube Data API v3 operations."""

from __future__ import annotations

import http.client
import random
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import httplib2
from googleapiclient.discovery import Resource
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from youtube_uploader.ids import parse_playlist_ref

CHUNK_SIZE = 8 * 1024 * 1024  # must be a multiple of 256 KiB
MAX_RETRIES = 10
RETRIABLE_STATUS_CODES = {500, 502, 503, 504}
RETRIABLE_EXCEPTIONS = (
    httplib2.HttpLib2Error,
    IOError,
    http.client.NotConnected,
    http.client.IncompleteRead,
    http.client.ImproperConnectionState,
    http.client.CannotSendRequest,
    http.client.CannotSendHeader,
    http.client.ResponseNotReady,
    http.client.BadStatusLine,
)


class ApiError(Exception):
    pass


# ---------------------------------------------------------------- upload


@dataclass
class VideoMetadata:
    title: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    category_id: str = "22"
    privacy: str = "private"
    made_for_kids: bool = False
    publish_at: str | None = None  # RFC 3339; requires privacy=private
    language: str | None = None

    def to_body(self) -> dict:
        snippet: dict = {
            "title": self.title,
            "description": self.description,
            "categoryId": self.category_id,
        }
        if self.tags:
            snippet["tags"] = self.tags
        if self.language:
            snippet["defaultLanguage"] = self.language
            snippet["defaultAudioLanguage"] = self.language
        status: dict = {
            "privacyStatus": self.privacy,
            "selfDeclaredMadeForKids": self.made_for_kids,
        }
        if self.publish_at:
            status["publishAt"] = self.publish_at
        return {"snippet": snippet, "status": status}


ProgressCallback = Callable[[int, int], None]
RetryCallback = Callable[[str, float, int], None]


def upload_video(
    yt: Resource,
    video_path: Path,
    metadata: VideoMetadata,
    on_progress: ProgressCallback | None = None,
    on_retry: RetryCallback | None = None,
) -> dict:
    """Upload a video using a resumable session. Returns the API video resource."""
    total = video_path.stat().st_size
    media = MediaFileUpload(str(video_path), chunksize=CHUNK_SIZE, resumable=True)
    request = yt.videos().insert(
        part="snippet,status",
        body=metadata.to_body(),
        media_body=media,
        notifySubscribers=metadata.privacy == "public",
    )

    response = None
    retry = 0
    while response is None:
        error: str | None = None
        try:
            status, response = request.next_chunk()
            if status is not None and on_progress:
                on_progress(status.resumable_progress, total)
            retry = 0
        except HttpError as e:
            if e.resp.status not in RETRIABLE_STATUS_CODES:
                raise
            error = f"HTTP {e.resp.status}"
        except RETRIABLE_EXCEPTIONS as e:
            error = repr(e)

        if error is not None:
            retry += 1
            if retry > MAX_RETRIES:
                raise ApiError(f"upload failed after {MAX_RETRIES} retries ({error})")
            delay = random.uniform(0, 2**retry)
            if on_retry:
                on_retry(error, delay, retry)
            time.sleep(delay)

    if on_progress:
        on_progress(total, total)
    return response


def set_thumbnail(yt: Resource, video_id: str, thumbnail: Path) -> None:
    yt.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumbnail))).execute()


# ---------------------------------------------------------------- videos


def _paginate(request_fn: Callable[..., object], limit: int | None, **kwargs) -> Iterator[dict]:
    token: str | None = None
    yielded = 0
    while True:
        resp = request_fn(pageToken=token, **kwargs).execute()
        for item in resp.get("items", []):
            yield item
            yielded += 1
            if limit is not None and yielded >= limit:
                return
        token = resp.get("nextPageToken")
        if not token:
            return


def uploads_playlist_id(yt: Resource) -> str:
    resp = yt.channels().list(part="contentDetails", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        raise ApiError("the authenticated account has no YouTube channel")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def get_videos(yt: Resource, video_ids: list[str]) -> list[dict]:
    """Fetch full video resources, preserving the order of video_ids."""
    found: dict[str, dict] = {}
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i : i + 50]
        resp = yt.videos().list(
            part="snippet,status,statistics,contentDetails", id=",".join(chunk)
        ).execute()
        for item in resp.get("items", []):
            found[item["id"]] = item
    return [found[v] for v in video_ids if v in found]


def get_video(yt: Resource, video_id: str) -> dict:
    videos = get_videos(yt, [video_id])
    if not videos:
        raise ApiError(f"video not found or not accessible: {video_id}")
    return videos[0]


def list_playlist_video_ids(yt: Resource, playlist_id: str, limit: int | None) -> list[str]:
    items = _paginate(
        yt.playlistItems().list,
        limit,
        part="contentDetails",
        playlistId=playlist_id,
        maxResults=50,
    )
    return [it["contentDetails"]["videoId"] for it in items]


def list_my_videos(yt: Resource, limit: int | None = 25) -> list[dict]:
    ids = list_playlist_video_ids(yt, uploads_playlist_id(yt), limit)
    return get_videos(yt, ids)


@dataclass
class VideoUpdate:
    title: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    category_id: str | None = None
    privacy: str | None = None
    publish_at: str | None = None
    made_for_kids: bool | None = None
    language: str | None = None

    def is_empty(self) -> bool:
        return all(v is None for v in self.__dict__.values())


def apply_update(video: dict, upd: VideoUpdate) -> dict:
    """Build a videos.update body from an existing resource plus changes.

    videos.update replaces whole parts: any snippet/status field not sent is
    reset, so the full current snippet and status are copied first.
    """
    snippet = dict(video["snippet"])
    for key in ("thumbnails", "localized", "channelId", "channelTitle", "publishedAt", "liveBroadcastContent"):
        snippet.pop(key, None)
    status = dict(video["status"])
    for key in ("uploadStatus", "failureReason", "rejectionReason", "madeForKids"):
        status.pop(key, None)

    if upd.title is not None:
        snippet["title"] = upd.title
    if upd.description is not None:
        snippet["description"] = upd.description
    if upd.tags is not None:
        snippet["tags"] = upd.tags
    if upd.category_id is not None:
        snippet["categoryId"] = upd.category_id
    if upd.language is not None:
        snippet["defaultLanguage"] = upd.language
        snippet["defaultAudioLanguage"] = upd.language
    if upd.made_for_kids is not None:
        status["selfDeclaredMadeForKids"] = upd.made_for_kids
    if upd.publish_at is not None:
        status["publishAt"] = upd.publish_at
        status["privacyStatus"] = "private"
    if upd.privacy is not None:
        status["privacyStatus"] = upd.privacy
    if status.get("privacyStatus") != "private":
        # Scheduling only applies to private videos; the API rejects it otherwise.
        status.pop("publishAt", None)

    return {"id": video["id"], "snippet": snippet, "status": status}


def update_video(yt: Resource, video_id: str, upd: VideoUpdate) -> dict:
    current = get_video(yt, video_id)
    body = apply_update(current, upd)
    return yt.videos().update(part="snippet,status", body=body).execute()


# ---------------------------------------------------------------- playlists


def list_my_playlists(yt: Resource, limit: int | None = None) -> list[dict]:
    return list(
        _paginate(
            yt.playlists().list,
            limit,
            part="snippet,status,contentDetails",
            mine=True,
            maxResults=50,
        )
    )


def resolve_playlist(yt: Resource, ref: str) -> str:
    """Resolve a playlist ID, URL or exact (case-insensitive) title to an ID."""
    value, is_id = parse_playlist_ref(ref)
    if is_id:
        return value
    matches = [
        p for p in list_my_playlists(yt) if p["snippet"]["title"].casefold() == value.casefold()
    ]
    if not matches:
        raise ApiError(f"no playlist titled {value!r} on your channel")
    if len(matches) > 1:
        ids = ", ".join(p["id"] for p in matches)
        raise ApiError(f"several playlists are titled {value!r}: {ids}; use an ID")
    return matches[0]["id"]


def create_playlist(yt: Resource, title: str, description: str = "", privacy: str = "private") -> dict:
    return yt.playlists().insert(
        part="snippet,status",
        body={
            "snippet": {"title": title, "description": description},
            "status": {"privacyStatus": privacy},
        },
    ).execute()


def add_to_playlist(yt: Resource, playlist_id: str, video_id: str) -> dict:
    return yt.playlistItems().insert(
        part="snippet",
        body={
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }
        },
    ).execute()


def remove_from_playlist(yt: Resource, playlist_id: str, video_id: str) -> int:
    """Remove every occurrence of video_id from the playlist; return how many."""
    items = _paginate(
        yt.playlistItems().list,
        None,
        part="id,contentDetails",
        playlistId=playlist_id,
        maxResults=50,
    )
    removed = 0
    for it in list(items):
        if it["contentDetails"]["videoId"] == video_id:
            yt.playlistItems().delete(id=it["id"]).execute()
            removed += 1
    return removed


def my_channel(yt: Resource) -> dict:
    resp = yt.channels().list(part="snippet,statistics", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        raise ApiError("the authenticated account has no YouTube channel")
    return items[0]
