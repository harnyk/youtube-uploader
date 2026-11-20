from youtube_uploader.api import VideoMetadata, VideoUpdate, apply_update


def _video(**status):
    return {
        "id": "abcdefghijk",
        "snippet": {
            "title": "Old",
            "description": "Old desc",
            "tags": ["x"],
            "categoryId": "22",
            "channelId": "UC1",
            "publishedAt": "2026-11-20T10:00:00Z",
            "thumbnails": {},
            "localized": {"title": "Old"},
        },
        "status": {
            "privacyStatus": "private",
            "uploadStatus": "processed",
            "embeddable": True,
            "license": "youtube",
            "madeForKids": False,
            "selfDeclaredMadeForKids": False,
            **status,
        },
    }


def test_update_keeps_unchanged_fields_and_strips_readonly():
    body = apply_update(_video(), VideoUpdate(title="New"))
    assert body["id"] == "abcdefghijk"
    assert body["snippet"] == {"title": "New", "description": "Old desc", "tags": ["x"], "categoryId": "22"}
    assert body["status"]["embeddable"] is True
    assert body["status"]["license"] == "youtube"
    for ro in ("uploadStatus", "madeForKids"):
        assert ro not in body["status"]


def test_update_privacy_public_drops_schedule():
    v = _video(publishAt="2026-12-01T18:00:00Z")
    body = apply_update(v, VideoUpdate(privacy="public"))
    assert body["status"]["privacyStatus"] == "public"
    assert "publishAt" not in body["status"]


def test_update_schedule_forces_private():
    v = _video(privacyStatus="unlisted")
    body = apply_update(v, VideoUpdate(publish_at="2026-12-01T18:00:00+01:00"))
    assert body["status"]["privacyStatus"] == "private"
    assert body["status"]["publishAt"] == "2026-12-01T18:00:00+01:00"


def test_update_language_sets_both_fields():
    body = apply_update(_video(), VideoUpdate(language="ru"))
    assert body["snippet"]["defaultLanguage"] == "ru"
    assert body["snippet"]["defaultAudioLanguage"] == "ru"


def test_video_update_is_empty():
    assert VideoUpdate().is_empty()
    assert not VideoUpdate(tags=[]).is_empty()


def test_metadata_body():
    body = VideoMetadata(title="T", tags=["a"], language="en", publish_at="2026-12-01T18:00:00+00:00").to_body()
    assert body["snippet"]["tags"] == ["a"]
    assert body["snippet"]["defaultLanguage"] == "en"
    assert body["status"] == {
        "privacyStatus": "private",
        "selfDeclaredMadeForKids": False,
        "publishAt": "2026-12-01T18:00:00+00:00",
    }
