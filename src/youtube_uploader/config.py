"""Configuration directory and user defaults (config.toml)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_ENV = "YTU_CONFIG_DIR"
PRIVACY_VALUES = ("private", "unlisted", "public")

CONFIG_TEMPLATE = """\
# youtube-uploader configuration.
# Values here are defaults for `ytu upload`; command-line flags override them.

[defaults]
# privacy = "private"        # private | unlisted | public
# category = "22"            # 22 = People & Blogs, 27 = Education, 28 = Science & Technology
# language = "en"            # default language of title/description and audio
# tags = ["tag1", "tag2"]
# playlist = ""              # playlist ID or exact title to add every upload to
# made_for_kids = false
# description_footer = ""    # text appended to every uploaded video's description
"""


def config_dir() -> Path:
    """Return the config directory: $YTU_CONFIG_DIR or $XDG_CONFIG_HOME/youtube-uploader."""
    if override := os.environ.get(CONFIG_ENV):
        return Path(override).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "youtube-uploader"


def client_secrets_path() -> Path:
    return config_dir() / "client_secret.json"


def token_path() -> Path:
    return config_dir() / "token.json"


def config_file_path() -> Path:
    return config_dir() / "config.toml"


class ConfigError(Exception):
    pass


@dataclass
class Defaults:
    privacy: str = "private"
    category: str = "22"
    language: str | None = None
    tags: list[str] = field(default_factory=list)
    playlist: str | None = None
    made_for_kids: bool = False
    description_footer: str = ""


def load_defaults(path: Path | None = None) -> Defaults:
    """Load [defaults] from config.toml; missing file means built-in defaults."""
    path = path or config_file_path()
    if not path.exists():
        return Defaults()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e

    raw = data.get("defaults", {})
    known = set(Defaults.__dataclass_fields__)
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(f"{path}: unknown keys in [defaults]: {', '.join(sorted(unknown))}")

    d = Defaults(**raw)
    if d.privacy not in PRIVACY_VALUES:
        raise ConfigError(f"{path}: privacy must be one of {', '.join(PRIVACY_VALUES)}")
    if not isinstance(d.tags, list) or not all(isinstance(t, str) for t in d.tags):
        raise ConfigError(f"{path}: tags must be a list of strings")
    d.category = str(d.category)
    d.playlist = d.playlist or None
    return d
