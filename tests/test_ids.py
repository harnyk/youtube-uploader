import pytest

from youtube_uploader.ids import parse_playlist_ref, parse_video_id

VID = "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "value",
    [
        VID,
        f"https://www.youtube.com/watch?v={VID}",
        f"https://www.youtube.com/watch?v={VID}&t=42s&list=PLxyz",
        f"youtube.com/watch?v={VID}",
        f"https://youtu.be/{VID}",
        f"https://youtu.be/{VID}?si=abc",
        f"https://www.youtube.com/shorts/{VID}",
        f"https://m.youtube.com/watch?v={VID}",
        f"https://www.youtube.com/embed/{VID}",
        f"https://www.youtube.com/live/{VID}",
        f"https://studio.youtube.com/video/{VID}/edit",
    ],
)
def test_parse_video_id(value):
    assert parse_video_id(value) == VID


@pytest.mark.parametrize(
    "value", ["", "short", "https://example.com/watch?v=dQw4w9WgXcQ", "https://youtube.com/channel/UCabc"]
)
def test_parse_video_id_rejects(value):
    with pytest.raises(ValueError):
        parse_video_id(value)


def test_parse_playlist_ref():
    pid = "PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"
    assert parse_playlist_ref(pid) == (pid, True)
    assert parse_playlist_ref(f"https://www.youtube.com/playlist?list={pid}") == (pid, True)
    assert parse_playlist_ref("My Tutorials") == ("My Tutorials", False)
