"""OAuth 2.0 authentication for the YouTube Data API."""

from __future__ import annotations

from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build

from youtube_uploader import config

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    # Needed for listing, editing metadata, thumbnails and playlists.
    "https://www.googleapis.com/auth/youtube",
]


class AuthError(Exception):
    pass


def _load_cached(token_file: Path) -> Credentials | None:
    if not token_file.exists():
        return None
    creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save(creds, token_file)
            return creds
        except RefreshError:
            return None
    return None


def _save(creds: Credentials, token_file: Path) -> None:
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json())
    token_file.chmod(0o600)


def login(client_secrets: Path | None = None, token_file: Path | None = None) -> Credentials:
    """Run the browser OAuth flow unconditionally and cache the token."""
    client_secrets = client_secrets or config.client_secrets_path()
    token_file = token_file or config.token_path()
    if not client_secrets.exists():
        raise AuthError(
            f"OAuth client secrets file not found: {client_secrets}\n"
            "Run `ytu auth login --client-secrets PATH` with the JSON downloaded from "
            "Google Cloud Console (OAuth client of type 'Desktop app')."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets), SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)
    _save(creds, token_file)
    return creds


def get_credentials(interactive: bool = True) -> Credentials:
    """Return valid credentials, running the OAuth flow if needed and allowed."""
    creds = _load_cached(config.token_path())
    if creds:
        return creds
    if not interactive:
        raise AuthError("Not logged in. Run `ytu auth login`.")
    return login()


def logout() -> bool:
    token = config.token_path()
    if token.exists():
        token.unlink()
        return True
    return False


def build_youtube(interactive: bool = True) -> Resource:
    creds = get_credentials(interactive=interactive)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)
