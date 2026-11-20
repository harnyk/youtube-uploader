# youtube-uploader (`ytu`)

Command-line tool to upload and manage your YouTube videos via the YouTube Data API v3:
resumable uploads with retries, listing uploads, editing titles/descriptions/tags/privacy,
scheduling, thumbnails and playlists.

## Install

Requires [uv](https://docs.astral.sh/uv/).

```sh
# Run once without installing
uvx --from git+https://github.com/harnyk/youtube-uploader ytu --help

# Install as a global command (`ytu` and `youtube-uploader`)
uv tool install git+https://github.com/harnyk/youtube-uploader

# Upgrade later
uv tool upgrade youtube-uploader
```

From a local checkout: `uv tool install .` (or `uv tool install -e .` for development).

## Google Cloud setup (once)

1. In [Google Cloud Console](https://console.cloud.google.com/) create a project and enable
   **YouTube Data API v3**.
2. **Google Auth Platform → Branding / Audience**: user type *External*, add your Google
   account under **Test users**.
3. **Clients → Create client → Desktop app**, download the JSON.
4. Sign in:

   ```sh
   ytu auth login --client-secrets ~/Downloads/client_secret_XXXX.json
   ```

   This copies the JSON into the config directory and opens a browser for consent.

While the app is in *Testing* status, Google expires the refresh token after 7 days and
`ytu` will ask you to sign in again. Publishing the app (Audience → Publish app) removes
that limit; for personal use verification is not required, you will just see an
"unverified app" warning on consent.

## Usage

```sh
ytu upload video.mp4 -t "My video" -d "Description" --tags "python,tutorial" -p unlisted
ytu upload video.mp4 -t "Premiere" --publish-at 2026-12-01T18:00:00+01:00 \
    --thumbnail thumb.jpg --playlist "My Tutorials"

ytu list -n 10                    # recent uploads
ytu show https://youtu.be/VIDEO   # metadata + description
ytu edit VIDEO -t "New title" -p public
ytu edit VIDEO -e                 # edit description in $EDITOR
ytu edit VIDEO -D description.txt --add-tags "extra,tags"
ytu edit VIDEO --append "Links: https://example.com"

ytu playlist list
ytu playlist create "My Tutorials" -p public
ytu playlist add "My Tutorials" VIDEO1 VIDEO2
ytu playlist remove PLxxxxxxxx VIDEO1
ytu playlist show "My Tutorials"

ytu auth status | login | logout
ytu config init | show | path
```

Videos accept a bare ID or any YouTube URL; playlists accept an ID, URL or exact title.
`upload` and `playlist create` print the new ID to stdout (progress goes to stderr), and
`list`, `show`, `playlist list/show` support `--json`, so the tool composes in scripts:

```sh
id=$(ytu upload clip.mp4 -t "Clip") && ytu playlist add "Clips" "$id"
```

Shell completion: `ytu --install-completion`.

## Configuration

Config directory: `$YTU_CONFIG_DIR`, else `$XDG_CONFIG_HOME/youtube-uploader`
(`~/.config/youtube-uploader`). It holds:

| File | Purpose |
|------|---------|
| `client_secret.json` | OAuth client (installed by `ytu auth login -c`) |
| `token.json` | cached OAuth token (mode 600) |
| `config.toml` | optional defaults for `ytu upload` |

`ytu config init` writes a commented template:

```toml
[defaults]
privacy = "unlisted"
category = "28"
language = "en"
tags = ["python"]
playlist = "My Tutorials"   # every upload is added here (skip with --no-playlist)
made_for_kids = false
description_footer = "Subscribe for more!"
```

Command-line flags always win over config values.

## Notes

- Uploads from an **unverified** Google Cloud project may be locked to `private` until the
  project passes a YouTube API audit.
- Default API quota is 10,000 units/day; uploads are by far the most expensive call.
- Custom thumbnails require a verified YouTube channel.
- Changes made with `edit` can take a few seconds to show up in `show`/`list`.

## Development

```sh
uv sync
uv run pytest
uv run ytu --help
```
