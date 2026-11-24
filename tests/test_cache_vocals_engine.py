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
    work = c.begin("abc")
    _fill(work)
    assert not c.is_complete("abc")
    c.commit("abc", {"title": "t"})
    assert c.is_complete("abc")
    assert c.read_meta("abc")["status"] == "complete"
    assert not work.exists()
    assert c.list_complete() == ["abc"]


def test_cache_commit_refuses_missing_files(tmp_path):
    c = Cache(tmp_path)
    c.begin("abc")
    with pytest.raises(RuntimeError):
        c.commit("abc", {})
    assert not c.is_complete("abc")


def test_incomplete_meta_is_not_a_hit(tmp_path):
    d = tmp_path / "abc"
    d.mkdir()
    _fill(d)
    (d / "meta.json").write_text(json.dumps({"status": "partial"}))
    assert not is_complete_dir(d)
    (d / "meta.json").write_text("{not json")
    assert not is_complete_dir(d)


def test_begin_discards_previous_partial(tmp_path):
    c = Cache(tmp_path)
    (c.begin("abc") / "junk").write_text("x")
    assert not (c.begin("abc") / "junk").exists()
    c.clear_staging()
    assert not (tmp_path / ".staging" / "abc").exists()


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


@pytest.mark.parametrize("prob,err,mode", [(0.8, False, "aligned"), (0.3, False, "teleprompter"), (None, False, "teleprompter"), (0.9, True, "teleprompter")])
def test_decide_alignment(prob, err, mode):
    assert engine.decide_alignment(prob, err) == mode


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
