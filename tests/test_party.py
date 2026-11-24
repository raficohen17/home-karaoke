import pytest

from karaoke.party import Duplicate, Party


def test_add_and_dedupe():
    p = Party()
    p.add("a")
    with pytest.raises(Duplicate):
        p.add("a")
    p.advance()  # a isn't ready -> stays queued, nothing current
    assert p.current is None and p.queue[0].video_id == "a"


def test_dedupe_against_current():
    p = Party()
    p.add("a", ready=True)
    p.advance()
    with pytest.raises(Duplicate):
        p.add("a")


def test_worker_is_fifo():
    p = Party()
    p.add("a")
    p.add("b")
    assert p.next_to_process().video_id == "a"
    p.set_status("a", "DOWNLOADING", 0.5)
    assert p.next_to_process().video_id == "b"
    p.set_status("b", "READY")
    assert p.next_to_process() is None


def test_advance_skips_failed_and_waits_for_processing():
    p = Party()
    p.add("bad")
    p.add("slow")
    p.add("ok")
    p.set_status("bad", "FAILED", reason="Video unavailable")
    p.set_status("slow", "SEPARATING")
    p.set_status("ok", "READY")
    assert p.advance().video_id == "ok"  # first READY wins over a still-processing song
    assert [e.video_id for e in p.queue] == ["slow"]
    assert p.advance() is None
    assert p.upcoming().video_id == "slow"


def test_remove_and_move():
    p = Party()
    a, b, c = p.add("a"), p.add("b"), p.add("c")
    assert p.move(c.id, -2)
    assert [e.video_id for e in p.queue] == ["c", "a", "b"]
    assert p.move(c.id, -5) and p.queue[0].video_id == "c"  # clamped
    assert p.remove(a.id) and not p.remove(a.id)
    assert [e.video_id for e in p.queue] == ["c", "b"]
    assert not p.move(999, 1)


def test_snapshot_shape():
    p = Party()
    p.add("a", title="A")
    s = p.snapshot()
    assert s["queue"][0]["title"] == "A" and s["upcoming"]["video_id"] == "a" and s["current"] is None


def test_set_status_rejects_unknown():
    p = Party()
    p.add("a")
    with pytest.raises(AssertionError):
        p.set_status("a", "WHATEVER")
