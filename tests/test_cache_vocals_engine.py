import json

import numpy as np
import pytest

from karaoke import engine, vocals
from karaoke.cache import REQUIRED_FILES, Cache, is_complete_dir
from karaoke.lrc import Line


def _fill(d):
    for f in REQUIRED_FILES:
        if f != "meta.json":
            (d / f).write_bytes(b"x")


def test_cache_commit_is_atomic(tmp_path):
    c = Cache(tmp_path)
    work = c.begin("abcdefghijk")
    _fill(work)
    assert not c.is_complete("abcdefghijk")
    c.commit("abcdefghijk", {"title": "t"})
    assert c.is_complete("abcdefghijk")
    assert c.read_meta("abcdefghijk")["status"] == "complete"
    assert not work.exists()
    assert c.list_complete() == ["abcdefghijk"]


def test_cache_commit_refuses_missing_files(tmp_path):
    c = Cache(tmp_path)
    c.begin("abcdefghijk")
    with pytest.raises(RuntimeError):
        c.commit("abcdefghijk", {})
    assert not c.is_complete("abcdefghijk")


def test_incomplete_meta_is_not_a_hit(tmp_path):
    d = tmp_path / "abcdefghijk"
    d.mkdir()
    _fill(d)
    (d / "meta.json").write_text(json.dumps({"status": "partial"}))
    assert not is_complete_dir(d)
    (d / "meta.json").write_text("{not json")
    assert not is_complete_dir(d)


def test_begin_discards_previous_partial(tmp_path):
    c = Cache(tmp_path)
    (c.begin("abcdefghijk") / "junk").write_text("x")
    assert not (c.begin("abcdefghijk") / "junk").exists()
    c.clear_staging()
    assert not (tmp_path / ".staging" / "abcdefghijk").exists()


def test_clear_staging_keeps_work_of_a_live_process(tmp_path):
    import os
    import subprocess
    import sys

    c = Cache(tmp_path)
    live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        busy = tmp_path / ".staging" / "busy"
        busy.mkdir(parents=True)
        (busy / ".owner_pid").write_text(str(live.pid))
        dead = tmp_path / ".staging" / "dead"
        dead.mkdir()
        (dead / ".owner_pid").write_text("999999")
        (tmp_path / ".staging" / "nopid").mkdir()
        c.clear_staging()
        assert busy.exists() and not dead.exists() and not (tmp_path / ".staging" / "nopid").exists()
    finally:
        live.kill()
    assert os.getpid()


def test_activity_and_onsets():
    sr = 1000
    t = np.arange(10 * sr) / sr
    sig = np.zeros_like(t)
    sig[(t >= 2) & (t < 7)] = np.sin(2 * np.pi * 220 * t[(t >= 2) & (t < 7)])
    act = vocals.activity_from_samples(sig, sr, hop=0.1)
    start, end = vocals.onsets(act)
    assert abs(start - 2.0) <= 0.1 and abs(end - 7.0) <= 0.1


def test_smooth_fills_short_gaps_and_drops_blips():
    a = np.array([0, 1, 1, 1, 0, 1, 1, 1, 0, 0, 0, 0, 1, 0, 0, 0], dtype=float)
    out = vocals.smooth(a, 3)
    assert list(out[1:8]) == [1] * 7  # gap of 1 filled
    assert out[12] == 0  # single blip removed


def test_onsets_silent():
    assert vocals.onsets(np.zeros(10)) == (None, None)


def test_guess_language():
    assert engine.guess_language("נועה קירל - מיליון דולר") == "he"
    assert engine.guess_language("Olivia Rodrigo - vampire") is None


# coverage measured 2026-11-24: פנתרה 0.74, ירח 0.67 (good); עטור מצחך live recording 0.04 (lost)
@pytest.mark.parametrize("cov,err,mode", [(0.74, False, "aligned"), (0.67, False, "aligned"), (0.04, False, "fallback"),
                                          (None, False, "fallback"), (0.9, True, "fallback")])
def test_decide_alignment(cov, err, mode):
    assert engine.decide_alignment(cov, err) == mode


def test_low_coverage_falls_back_to_transcription(monkeypatch, tmp_path):
    import soundfile as sf
    from karaoke import align, sources

    sr = 8000
    sig = np.zeros(sr * 10, dtype=np.float32); sig[sr * 2: sr * 8] = 0.3
    sf.write(str(tmp_path / "v.flac"), sig, sr)
    monkeypatch.setattr(sources, "fetch_lrclib", lambda name, d=None: [sources.LrclibHit("שיר", "זמר", 300.0, None, "שורה אחת\nשורה שתיים")])
    monkeypatch.setattr(align, "align_words", lambda v, text, lang: ([(1.0, "שורה", 0.1), (9.0, "אחת", 0.1)], 0.1))
    monkeypatch.setattr(align, "transcribe_lines", lambda v, lang: [Line(2.0, "שורה אחת", ((2.0, "שורה"), (2.4, "אחת")))])
    res = engine.build_lyrics({"title": "זמר - שיר", "channel": "x", "duration": 10}, tmp_path / "v.flac")
    assert res.mode == "transcribed" and res.lines[0].words[1] == (2.4, "אחת") and res.align_coverage == 0.0


def test_good_coverage_keeps_text_with_word_times(monkeypatch, tmp_path):
    import soundfile as sf
    from karaoke import align, sources

    sr = 8000
    sig = np.zeros(sr * 10, dtype=np.float32); sig[sr * 2: sr * 8] = 0.3
    sf.write(str(tmp_path / "v.flac"), sig, sr)
    monkeypatch.setattr(sources, "fetch_lrclib", lambda name, d=None: [sources.LrclibHit("שיר", "זמר", 300.0, None, "שורה אחת\nשורה שתיים")])
    monkeypatch.setattr(align, "align_words", lambda v, text, lang: (
        [(2.0, "שורה", 0.9), (2.5, "אחת", 0.9), (5.0, "שורה", 0.9), (5.5, "שתיים", 0.2)], 0.7))
    res = engine.build_lyrics({"title": "זמר - שיר", "channel": "x", "duration": 10}, tmp_path / "v.flac")
    assert res.mode == "aligned" and [l.t for l in res.lines] == [2.0, 5.0]
    assert res.lines[1].words[1][1] == "שתיים" and 5.0 < res.lines[1].words[1][0]


def test_correct_synced_shifts_lines():
    hop = 0.1
    act = np.zeros(400)
    act[150:180] = 1  # vocals at 15-18s
    lines, off = engine.correct_synced([Line(10.0, "a")], act, hop)
    assert abs(off - 5.0) <= 0.2 and abs(lines[0].t - 15.0) <= 0.2


def test_classify_pasted():
    assert engine.classify_pasted("[00:01.00]a\n[00:02.00]b\n[00:03.00]c") == "lrc"
    assert engine.classify_pasted("line one\nline two\n[Chorus]\nline three") == "text"
    assert engine.classify_pasted("[00:01.00]only one timed line\nrest plain") == "text"


def test_write_lyrics_replaces_previous_format(tmp_path):
    (tmp_path / "lyrics.lrc").write_text("[00:01.00]old")
    engine.write_lyrics(engine.LyricsResult(mode="teleprompter", text="new"), tmp_path)
    assert not (tmp_path / "lyrics.lrc").exists() and (tmp_path / "lyrics.txt").read_text() == "new"


def test_vote_language():
    from karaoke.align import vote_language
    # first window fooled by an English ad-lib; the song is Hebrew
    w = [[("en", 0.61), ("he", 0.05)], [("he", 0.73), ("en", 0.21)], [("he", 0.61), ("en", 0.32)]]
    assert vote_language(w) == "he"
    assert vote_language([[("en", 0.9)], [("en", 0.8), ("he", 0.1)]]) == "en"
    assert vote_language([]) == "en"
