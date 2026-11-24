from pathlib import Path

from karaoke.sources import (
    LrclibHit,
    SongName,
    choose_lrclib,
    choose_shironet,
    has_hebrew,
    normalize,
    parse_lrclib,
    parse_shironet_lyrics,
    parse_shironet_search,
    similarity,
    song_name_from_youtube,
)

FIX = Path(__file__).parent / "fixtures"


def test_normalize_hebrew_spelling_variants():
    assert normalize("מליון דולר") == normalize("מיליון דולר")
    assert normalize("גֻּושְׁפַּנְקָא") == normalize("גשפנקא")


def test_has_hebrew():
    assert has_hebrew("נועה קירל") and not has_hebrew("Olivia Rodrigo")


def test_song_name_hebrew_title_with_guest_and_alias():
    n = song_name_from_youtube(
        "נועה קירל - מיליון דולר מארחת את שחר סאול - Million Dollar (Prod. by Jordi) | Noa Kirel", "Noa Kirel"
    )
    assert (n.artist, n.title) == ("נועה קירל", "מיליון דולר")
    assert "Million Dollar" in n.titles() and "Noa Kirel" in n.artists()


def test_song_name_english_official_video():
    n = song_name_from_youtube("Olivia Rodrigo - vampire (Official Video)", "Olivia Rodrigo")
    assert (n.artist, n.title, n.titles(), n.artists()) == ("Olivia Rodrigo", "vampire", ["vampire"], ["Olivia Rodrigo"])


def test_song_name_topic_channel():
    n = song_name_from_youtube("vampire", "Olivia Rodrigo - Topic")
    assert (n.artist, n.title) == ("Olivia Rodrigo", "vampire")


def test_song_name_music_metadata_wins():
    n = song_name_from_youtube("whatever", "x", track="vampire", artist="Olivia Rodrigo")
    assert (n.artist, n.title) == ("Olivia Rodrigo", "vampire")


def test_song_name_hebrew_with_inline_english_alias():
    n = song_name_from_youtube("עומר אדם - תל אביב Tel Aviv", "Omer Adam")
    assert (n.title, n.alt_titles) == ("תל אביב", ("Tel Aviv",))


def test_lrclib_finds_song_under_english_alias():
    name = SongName("נועה קירל", "מיליון דולר", ("Noa Kirel",), ("Million Dollar",))
    hits = [LrclibHit("Million Dollar", "Noa Kirel", 174.0, "[00:01.00]x", "x"), LrclibHit("מליון דולר", "Tuna", 174.0, "[00:01.00]y", "y")]
    synced, _ = choose_lrclib(hits, name, 174.0)
    assert synced.artist == "Noa Kirel"  # same title and length by another artist is rejected


def test_lrclib_queries_try_aliases():
    from karaoke.sources import lrclib_queries
    qs = lrclib_queries(SongName("נועה קירל", "מיליון דולר", ("Noa Kirel",), ("Million Dollar",)))
    assert {"track_name": "Million Dollar", "artist_name": "Noa Kirel"} in qs


def test_parse_lrclib_skips_instrumentals():
    hits = parse_lrclib([
        {"trackName": "a", "artistName": "b", "duration": 1, "syncedLyrics": "[00:01.00]x", "plainLyrics": "x"},
        {"trackName": "c", "artistName": "d", "instrumental": True},
    ])
    assert len(hits) == 1 and hits[0].synced == "[00:01.00]x"


def _hit(track="vampire", artist="Olivia Rodrigo", dur=220.0, synced="[00:01.00]x", plain="x"):
    return LrclibHit(track, artist, dur, synced, plain)


def test_choose_lrclib_synced_needs_duration_match():
    name = SongName("Olivia Rodrigo", "vampire")
    synced, plain = choose_lrclib([_hit(dur=220.0)], name, 245.0)
    assert synced is None and plain is not None  # video is 25s longer: align plain text instead


def test_choose_lrclib_picks_closest_duration():
    name = SongName("Olivia Rodrigo", "vampire")
    synced, _ = choose_lrclib([_hit(dur=220.0), _hit(dur=244.0)], name, 245.0)
    assert synced.duration == 244.0


def test_choose_lrclib_ignores_other_titles():
    synced, plain = choose_lrclib([_hit(track="drivers license")], SongName("Olivia Rodrigo", "vampire"), 220.0)
    assert synced is None and plain is None


def test_shironet_search_and_choose():
    results = parse_shironet_search((FIX / "shironet_search.html").read_text())
    assert results[0].title == "מיליון דולר" and results[0].artist == "מאור פרץ"
    assert choose_shironet(results, SongName("נועה קירל", "מיליון דולר")) is None  # not her song
    assert choose_shironet(results, SongName("מאור פרץ", "מליון דולר")).href.endswith("wrkid=36546")


def test_shironet_lyrics():
    text = parse_shironet_lyrics((FIX / "shironet_lyrics.html").read_text())
    assert text.splitlines() == ["שורה ראשונה של בדיקה", "שורה שנייה, עם פסיק!", "third line in English"]
    assert parse_shironet_lyrics("<html></html>") is None


def test_similarity_bounds():
    assert similarity("vampire", "Vampire") == 1.0
    assert similarity("vampire", "drivers license") < 0.5
