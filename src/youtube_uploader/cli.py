"""Command-line interface (`ytu` / `youtube-uploader`)."""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Optional

import typer
from googleapiclient.errors import HttpError
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table

from youtube_uploader import api, auth, config
from youtube_uploader.ids import parse_video_id

out = Console(highlight=False)
err = Console(stderr=True, highlight=False)

app = typer.Typer(
    help="Upload and manage your YouTube videos from the command line.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)
playlist_app = typer.Typer(help="List, create and edit playlists.", no_args_is_help=True)
auth_app = typer.Typer(help="Manage Google sign-in.", no_args_is_help=True)
config_app = typer.Typer(help="Inspect and create the config file.", no_args_is_help=True)
app.add_typer(playlist_app, name="playlist")
app.add_typer(auth_app, name="auth")
app.add_typer(config_app, name="config")


class Privacy(StrEnum):
    private = "private"
    unlisted = "unlisted"
    public = "public"


# ---------------------------------------------------------------- helpers


def _yt():
    return auth.build_youtube()


def _video_id(value: str) -> str:
    try:
        return parse_video_id(value)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e


def _rfc3339(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as e:
        raise typer.BadParameter(f"invalid datetime: {value!r}") from e
    if dt.tzinfo is None:
        raise typer.BadParameter("datetime must include a timezone, e.g. 2026-12-01T18:00:00+01:00")
    return dt.isoformat()


def _split_tags(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [t.strip() for t in value.split(",") if t.strip()]


def _print_json(data: object) -> None:
    out.print_json(json.dumps(data, ensure_ascii=False))


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return ""
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")


def _fmt_duration(iso: str) -> str:
    # ISO 8601 duration like PT1H2M3S -> 1:02:03
    import re

    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return iso or ""
    d, h, mi, s = (int(x or 0) for x in m.groups())
    h += d * 24
    return f"{h}:{mi:02}:{s:02}" if h else f"{mi}:{s:02}"


def _privacy_label(status: dict) -> str:
    label = status.get("privacyStatus", "")
    if status.get("publishAt"):
        label += f" → {_fmt_date(status['publishAt'])}"
    return label


ExistingFile = Annotated[Path, typer.Argument(exists=True, dir_okay=False, resolve_path=True)]


# ---------------------------------------------------------------- upload


@app.command()
def upload(
    video: ExistingFile,
    title: Annotated[Optional[str], typer.Option("-t", "--title", help="Title (default: file name).")] = None,
    description: Annotated[Optional[str], typer.Option("-d", "--description", help="Description text.")] = None,
    description_file: Annotated[
        Optional[Path], typer.Option("--description-file", "-D", exists=True, dir_okay=False, help="Read description from a file.")
    ] = None,
    tags: Annotated[Optional[str], typer.Option("--tags", help="Comma-separated tags.")] = None,
    category: Annotated[Optional[str], typer.Option("--category", help="Category ID (22 People & Blogs, 27 Education, 28 Sci & Tech).")] = None,
    privacy: Annotated[Optional[Privacy], typer.Option("-p", "--privacy", help="Privacy status.")] = None,
    publish_at: Annotated[Optional[str], typer.Option("--publish-at", help="Schedule (ISO 8601 with timezone); forces private.")] = None,
    made_for_kids: Annotated[Optional[bool], typer.Option("--made-for-kids/--not-for-kids", help="Audience declaration.")] = None,
    language: Annotated[Optional[str], typer.Option("--language", help="Language code, e.g. en, ru.")] = None,
    thumbnail: Annotated[Optional[Path], typer.Option("--thumbnail", exists=True, dir_okay=False, help="Custom thumbnail (JPG/PNG).")] = None,
    playlist: Annotated[Optional[str], typer.Option("--playlist", help="Playlist ID, URL or exact title to add the video to.")] = None,
    no_playlist: Annotated[bool, typer.Option("--no-playlist", help="Ignore the default playlist from config.")] = False,
) -> None:
    """Upload a video. Prints the new video ID to stdout."""
    if description is not None and description_file is not None:
        raise typer.BadParameter("use either --description or --description-file")

    defaults = config.load_defaults()
    desc = description_file.read_text(encoding="utf-8") if description_file else (description or "")
    if defaults.description_footer:
        desc = f"{desc.rstrip()}\n\n{defaults.description_footer}".lstrip()

    schedule = _rfc3339(publish_at)
    priv = (privacy.value if privacy else None) or defaults.privacy
    if schedule and priv != "private":
        err.print("[yellow]note:[/] --publish-at requires private; overriding privacy")
        priv = "private"

    meta = api.VideoMetadata(
        title=title or video.stem,
        description=desc,
        tags=_split_tags(tags) if tags is not None else defaults.tags,
        category_id=category or defaults.category,
        privacy=priv,
        made_for_kids=defaults.made_for_kids if made_for_kids is None else made_for_kids,
        publish_at=schedule,
        language=language or defaults.language,
    )
    target_playlist = None if no_playlist else (playlist or defaults.playlist)

    yt = _yt()
    # Resolve the playlist before uploading so a typo doesn't waste an upload.
    playlist_id = api.resolve_playlist(yt, target_playlist) if target_playlist else None

    err.print(f"Uploading [bold]{video.name}[/] as [bold]{meta.title!r}[/] ({_privacy_label(meta.to_body()['status'])})")
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        DownloadColumn(binary_units=True),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=err,
        transient=False,
    ) as progress:
        task = progress.add_task("upload", total=video.stat().st_size)
        result = api.upload_video(
            yt,
            video,
            meta,
            on_progress=lambda done, total: progress.update(task, completed=done),
            on_retry=lambda e, delay, n: progress.console.print(
                f"[yellow]{e}[/]; retry {n}/{api.MAX_RETRIES} in {delay:.1f}s"
            ),
        )

    video_id = result["id"]
    err.print(f"[green]Uploaded:[/] https://youtu.be/{video_id}")
    if thumbnail:
        api.set_thumbnail(yt, video_id, thumbnail)
        err.print("Thumbnail set.")
    if playlist_id:
        api.add_to_playlist(yt, playlist_id, video_id)
        err.print(f"Added to playlist {playlist_id}.")
    print(video_id)


# ---------------------------------------------------------------- list / show / edit


@app.command("list")
def list_videos(
    limit: Annotated[int, typer.Option("-n", "--limit", min=1, help="How many recent uploads to show.")] = 25,
    as_json: Annotated[bool, typer.Option("--json", help="Output raw JSON.")] = False,
) -> None:
    """List your recent uploads (newest first)."""
    videos = api.list_my_videos(_yt(), limit)
    if as_json:
        _print_json(videos)
        return
    table = Table(box=None, header_style="bold")
    table.add_column("ID", no_wrap=True)
    table.add_column("Published", no_wrap=True)
    table.add_column("Privacy", no_wrap=True)
    table.add_column("Length", justify="right", no_wrap=True)
    table.add_column("Views", justify="right", no_wrap=True)
    table.add_column("Title")
    for v in videos:
        table.add_row(
            v["id"],
            _fmt_date(v["snippet"].get("publishedAt")),
            _privacy_label(v["status"]),
            _fmt_duration(v.get("contentDetails", {}).get("duration", "")),
            v.get("statistics", {}).get("viewCount", ""),
            v["snippet"]["title"],
        )
    out.print(table)


@app.command()
def show(
    video: Annotated[str, typer.Argument(help="Video ID or URL.")],
    as_json: Annotated[bool, typer.Option("--json", help="Output raw JSON.")] = False,
) -> None:
    """Show a video's metadata and description."""
    v = api.get_video(_yt(), _video_id(video))
    if as_json:
        _print_json(v)
        return
    sn, st = v["snippet"], v["status"]
    stats = v.get("statistics", {})
    rows = [
        ("URL", f"https://youtu.be/{v['id']}"),
        ("Title", sn["title"]),
        ("Published", _fmt_date(sn.get("publishedAt"))),
        ("Privacy", _privacy_label(st)),
        ("Duration", _fmt_duration(v.get("contentDetails", {}).get("duration", ""))),
        ("Category", sn.get("categoryId", "")),
        ("Language", sn.get("defaultLanguage", "")),
        ("Tags", ", ".join(sn.get("tags", []))),
        ("Made for kids", str(st.get("selfDeclaredMadeForKids", st.get("madeForKids", "")))),
        ("Views / likes / comments", f"{stats.get('viewCount', '-')} / {stats.get('likeCount', '-')} / {stats.get('commentCount', '-')}"),
    ]
    table = Table(box=None, show_header=False)
    table.add_column(style="bold", no_wrap=True)
    table.add_column()
    for k, val in rows:
        table.add_row(k, val)
    out.print(table)
    out.print()
    out.rule("Description", style="dim")
    out.print(sn.get("description") or "[dim](empty)[/]", markup=not sn.get("description"))


@app.command()
def edit(
    video: Annotated[str, typer.Argument(help="Video ID or URL.")],
    title: Annotated[Optional[str], typer.Option("-t", "--title", help="New title.")] = None,
    description: Annotated[Optional[str], typer.Option("-d", "--description", help="Replace the description.")] = None,
    description_file: Annotated[
        Optional[Path], typer.Option("--description-file", "-D", exists=True, dir_okay=False, help="Replace the description from a file.")
    ] = None,
    editor: Annotated[bool, typer.Option("-e", "--editor", help="Edit the description in $EDITOR.")] = False,
    append: Annotated[Optional[str], typer.Option("--append", help="Append a paragraph to the description.")] = None,
    tags: Annotated[Optional[str], typer.Option("--tags", help="Replace tags (comma-separated; empty string clears).")] = None,
    add_tags: Annotated[Optional[str], typer.Option("--add-tags", help="Add comma-separated tags.")] = None,
    category: Annotated[Optional[str], typer.Option("--category", help="Category ID.")] = None,
    privacy: Annotated[Optional[Privacy], typer.Option("-p", "--privacy", help="Privacy status.")] = None,
    publish_at: Annotated[Optional[str], typer.Option("--publish-at", help="Schedule (ISO 8601 with timezone); makes the video private.")] = None,
    made_for_kids: Annotated[Optional[bool], typer.Option("--made-for-kids/--not-for-kids", help="Audience declaration.")] = None,
    language: Annotated[Optional[str], typer.Option("--language", help="Language code.")] = None,
    thumbnail: Annotated[Optional[Path], typer.Option("--thumbnail", exists=True, dir_okay=False, help="Replace the thumbnail.")] = None,
) -> None:
    """Change a video's title, description, tags, privacy and more."""
    if sum([description is not None, description_file is not None, editor]) > 1:
        raise typer.BadParameter("use only one of --description, --description-file, --editor")

    yt = _yt()
    vid = _video_id(video)
    current = api.get_video(yt, vid)
    sn = current["snippet"]

    new_desc: str | None = None
    if description is not None:
        new_desc = description
    elif description_file is not None:
        new_desc = description_file.read_text(encoding="utf-8")
    elif editor:
        edited = typer.edit(sn.get("description", ""), extension=".txt", require_save=True)
        if edited is None:
            err.print("Description unchanged (editor closed without saving).")
        else:
            new_desc = edited.rstrip("\n")
    if append is not None:
        base = new_desc if new_desc is not None else sn.get("description", "")
        new_desc = f"{base.rstrip()}\n\n{append}".lstrip()

    new_tags = _split_tags(tags)
    if add_tags is not None:
        base_tags = new_tags if new_tags is not None else list(sn.get("tags", []))
        new_tags = base_tags + [t for t in _split_tags(add_tags) or [] if t not in base_tags]

    upd = api.VideoUpdate(
        title=title,
        description=new_desc,
        tags=new_tags,
        category_id=category,
        privacy=privacy.value if privacy else None,
        publish_at=_rfc3339(publish_at),
        made_for_kids=made_for_kids,
        language=language,
    )

    if upd.is_empty() and not thumbnail:
        err.print("Nothing to change.")
        raise typer.Exit(0)

    if not upd.is_empty():
        body = api.apply_update(current, upd)
        yt.videos().update(part="snippet,status", body=body).execute()
        changed = [k for k, v in upd.__dict__.items() if v is not None]
        err.print(f"[green]Updated[/] {vid}: {', '.join(changed)}")
    if thumbnail:
        api.set_thumbnail(yt, vid, thumbnail)
        err.print("[green]Thumbnail set.[/]")


# ---------------------------------------------------------------- playlists


@playlist_app.command("list")
def playlist_list(as_json: Annotated[bool, typer.Option("--json", help="Output raw JSON.")] = False) -> None:
    """List your playlists."""
    playlists = api.list_my_playlists(_yt())
    if as_json:
        _print_json(playlists)
        return
    table = Table(box=None, header_style="bold")
    table.add_column("ID", no_wrap=True)
    table.add_column("Privacy", no_wrap=True)
    table.add_column("Videos", justify="right")
    table.add_column("Title")
    for p in playlists:
        table.add_row(
            p["id"],
            p["status"]["privacyStatus"],
            str(p["contentDetails"]["itemCount"]),
            p["snippet"]["title"],
        )
    out.print(table)


@playlist_app.command("show")
def playlist_show(
    playlist: Annotated[str, typer.Argument(help="Playlist ID, URL or exact title.")],
    limit: Annotated[Optional[int], typer.Option("-n", "--limit", min=1, help="Max videos to show.")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output raw JSON.")] = False,
) -> None:
    """List the videos in a playlist."""
    yt = _yt()
    pid = api.resolve_playlist(yt, playlist)
    videos = api.get_videos(yt, api.list_playlist_video_ids(yt, pid, limit))
    if as_json:
        _print_json(videos)
        return
    table = Table(box=None, header_style="bold")
    table.add_column("#", justify="right")
    table.add_column("ID", no_wrap=True)
    table.add_column("Privacy", no_wrap=True)
    table.add_column("Title")
    for i, v in enumerate(videos, 1):
        table.add_row(str(i), v["id"], _privacy_label(v["status"]), v["snippet"]["title"])
    out.print(table)


@playlist_app.command("create")
def playlist_create(
    title: Annotated[str, typer.Argument(help="Playlist title.")],
    description: Annotated[str, typer.Option("-d", "--description", help="Playlist description.")] = "",
    privacy: Annotated[Privacy, typer.Option("-p", "--privacy", help="Privacy status.")] = Privacy.private,
) -> None:
    """Create a playlist. Prints its ID to stdout."""
    p = api.create_playlist(_yt(), title, description, privacy.value)
    err.print(f"[green]Created[/] playlist {title!r} ({privacy.value})")
    print(p["id"])


@playlist_app.command("add")
def playlist_add(
    playlist: Annotated[str, typer.Argument(help="Playlist ID, URL or exact title.")],
    videos: Annotated[list[str], typer.Argument(help="One or more video IDs or URLs.")],
) -> None:
    """Add videos to a playlist."""
    yt = _yt()
    pid = api.resolve_playlist(yt, playlist)
    for v in videos:
        vid = _video_id(v)
        api.add_to_playlist(yt, pid, vid)
        err.print(f"[green]Added[/] {vid} to {pid}")


@playlist_app.command("remove")
def playlist_remove(
    playlist: Annotated[str, typer.Argument(help="Playlist ID, URL or exact title.")],
    videos: Annotated[list[str], typer.Argument(help="One or more video IDs or URLs.")],
) -> None:
    """Remove videos from a playlist (the videos themselves are kept)."""
    yt = _yt()
    pid = api.resolve_playlist(yt, playlist)
    for v in videos:
        vid = _video_id(v)
        n = api.remove_from_playlist(yt, pid, vid)
        if n:
            err.print(f"[green]Removed[/] {vid} from {pid}")
        else:
            err.print(f"[yellow]{vid} is not in {pid}[/]")


# ---------------------------------------------------------------- auth


@auth_app.command("login")
def auth_login(
    client_secrets: Annotated[
        Optional[Path],
        typer.Option("--client-secrets", "-c", exists=True, dir_okay=False, help="OAuth client JSON to install into the config dir."),
    ] = None,
) -> None:
    """Sign in with Google (opens a browser). Optionally installs the OAuth client JSON."""
    if client_secrets:
        dest = config.client_secrets_path()
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(client_secrets, dest)
        dest.chmod(0o600)
        err.print(f"Installed client secrets to {dest}")
    auth.login()
    ch = api.my_channel(auth.build_youtube(interactive=False))
    err.print(f"[green]Logged in[/] as channel [bold]{ch['snippet']['title']}[/]")


@auth_app.command("logout")
def auth_logout() -> None:
    """Delete the cached token."""
    if auth.logout():
        err.print(f"Removed {config.token_path()}")
    else:
        err.print("Not logged in.")


@auth_app.command("status")
def auth_status() -> None:
    """Show which channel you are signed in as."""
    ch = api.my_channel(auth.build_youtube(interactive=False))
    stats = ch.get("statistics", {})
    out.print(f"Channel: [bold]{ch['snippet']['title']}[/] ({ch['id']})")
    out.print(f"Videos: {stats.get('videoCount', '?')}, subscribers: {stats.get('subscriberCount', 'hidden')}")


# ---------------------------------------------------------------- config


@config_app.command("path")
def config_path() -> None:
    """Print the config directory."""
    print(config.config_dir())


@config_app.command("init")
def config_init(force: Annotated[bool, typer.Option("--force", help="Overwrite an existing file.")] = False) -> None:
    """Create a commented config.toml template."""
    path = config.config_file_path()
    if path.exists() and not force:
        err.print(f"{path} already exists (use --force to overwrite)")
        raise typer.Exit(1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config.CONFIG_TEMPLATE, encoding="utf-8")
    err.print(f"Wrote {path}")


@config_app.command("show")
def config_show() -> None:
    """Show config files and effective defaults."""
    d = config.load_defaults()
    for label, p in (
        ("Config dir", config.config_dir()),
        ("Config file", config.config_file_path()),
        ("Client secrets", config.client_secrets_path()),
        ("Token", config.token_path()),
    ):
        mark = "[green]✓[/]" if p.exists() else "[red]✗[/]"
        out.print(f"{mark} {label}: {p}")
    out.print()
    _print_json(d.__dict__)


# ---------------------------------------------------------------- entry point


def _http_error_message(e: HttpError) -> str:
    try:
        payload = json.loads(e.content)
        error = payload.get("error", {})
        msg = error.get("message") or e.reason
        reasons = {d.get("reason") for d in error.get("errors", []) if d.get("reason")}
        if reasons:
            msg += f" [{', '.join(sorted(reasons))}]"
        return f"YouTube API error {e.resp.status}: {msg}"
    except (ValueError, AttributeError):
        return f"YouTube API error {e.resp.status}: {e.reason}"


def main() -> None:
    try:
        app()
    except HttpError as e:
        err.print(f"[red]{_http_error_message(e)}[/]")
        sys.exit(1)
    except (api.ApiError, auth.AuthError, config.ConfigError) as e:
        err.print(f"[red]error:[/] {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        err.print("\naborted")
        sys.exit(130)
