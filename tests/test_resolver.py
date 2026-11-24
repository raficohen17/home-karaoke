from pathlib import Path

import pytest

from karaoke.resolver import (
    Candidate,
    NoMatch,
    classify_input,
    parse_spotify_page,
    pick_candidate,
    spotify_track_id,
    youtube_video_id,
)

FIX = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=RlPNh_PBZb4",
        "https://youtube.com/watch?v=RlPNh_PBZb4&t=10s",
        "https://youtu.be/RlPNh_PBZb4?si=abc",
        "https://www.youtube.com/shorts/RlPNh_PBZb4",
        "https://music.youtube.com/watch?v=RlPNh_PBZb4&list=x",
        "https://m.youtube.com/embed/RlPNh_PBZb4",
    ],
)
def test_youtube_ids(url):
    assert youtube_video_id(url) == "RlPNh_PBZb4"


@pytest.mark.parametrize("url", ["https://www.youtube.com/watch?v=short", "https://vimeo.com/123", "olivia rodrigo vampire"])
def test_youtube_rejects(url):
    assert youtube_video_id(url) is None


def test_spotify_ids():
    assert spotify_track_id("https://open.spotify.com/track/1kuGVB7EU95pJObxwvfwKS?si=x") == "1kuGVB7EU95pJObxwvfwKS"
    assert spotify_track_id("https://open.spotify.com/intl-he/track/1kuGVB7EU95pJObxwvfwKS") == "1kuGVB7EU95pJObxwvfwKS"
    assert spotify_track_id("https://open.spotify.com/album/1kuGVB7EU95pJObxwvfwKS") is None


def test_classify():
    assert classify_input("https://youtu.be/RlPNh_PBZb4") == "youtube"
    assert classify_input("https://open.spotify.com/track/1kuGVB7EU95pJObxwvfwKS") == "spotify"
    assert classify_input("נועה קירל מליון דולר") == "query"


def test_parse_spotify_page():
    t = parse_spotify_page((FIX / "spotify_track.html").read_text())
    assert (t.title, t.artist, t.duration) == ("vampire", "Olivia Rodrigo", 219.0)


def test_parse_spotify_page_without_title():
    with pytest.raises(ValueError):
        parse_spotify_page("<html></html>")


def _c(vid, dur, title="x", channel="c", views=None):
    return Candidate(vid, title, channel, dur, views)


def test_pick_prefers_duration_match():
    cands = [_c("video", 245, "Olivia Rodrigo - vampire (Official Video)"), _c("audio", 220, "vampire (Official Audio)")]
    assert pick_candidate(cands, 219).video_id == "audio"


def test_pick_penalises_live_and_covers():
    cands = [_c("live", 220, "vampire (Live)"), _c("lyric", 221, "vampire (Lyric Video)")]
    assert pick_candidate(cands, 220).video_id == "lyric"


def test_pick_no_match_when_durations_far():
    with pytest.raises(NoMatch):
        pick_candidate([_c("a", 300), _c("b", 100)], 220)


def test_pick_no_results():
    with pytest.raises(NoMatch):
        pick_candidate([], None)


def test_pick_without_duration_uses_hints():
    cands = [_c("cover", 200, "song (cover)"), _c("topic", 200, "song", "Artist - Topic")]
    assert pick_candidate(cands, None).video_id == "topic"
