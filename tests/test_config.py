import pytest

from youtube_uploader import config


def test_config_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv(config.CONFIG_ENV, str(tmp_path))
    assert config.config_dir() == tmp_path
    assert config.token_path() == tmp_path / "token.json"


def test_config_dir_xdg(monkeypatch, tmp_path):
    monkeypatch.delenv(config.CONFIG_ENV, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config.config_dir() == tmp_path / "youtube-uploader"


def test_missing_file_gives_defaults(tmp_path):
    assert config.load_defaults(tmp_path / "none.toml") == config.Defaults()


def test_template_parses_to_defaults(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(config.CONFIG_TEMPLATE)
    assert config.load_defaults(p) == config.Defaults()


def test_load_values(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[defaults]\nprivacy = "unlisted"\ncategory = 28\ntags = ["a", "b"]\nplaylist = ""\n')
    d = config.load_defaults(p)
    assert d.privacy == "unlisted"
    assert d.category == "28"
    assert d.tags == ["a", "b"]
    assert d.playlist is None


@pytest.mark.parametrize(
    "body",
    ['[defaults]\nprivacy = "secret"\n', '[defaults]\nbogus = 1\n', '[defaults]\ntags = "a,b"\n', "not toml ["],
)
def test_invalid(tmp_path, body):
    p = tmp_path / "config.toml"
    p.write_text(body)
    with pytest.raises(config.ConfigError):
        config.load_defaults(p)
