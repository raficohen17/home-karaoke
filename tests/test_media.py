from pathlib import Path

import numpy as np

from karaoke.media import pick_stems, rebalance


def _sig(n=44100, f=220.0, amp=0.3):
    t = np.arange(n) / 44100
    return (amp * np.sin(2 * np.pi * f * t)).astype(np.float32)[:, None].repeat(2, 1)


def test_rebalance_restores_levels_after_peak_normalisation():
    inst, voc = _sig(f=110, amp=0.4), _sig(f=440, amp=0.2)
    mix = inst + voc
    i2, v2 = rebalance(mix, inst * 0.84, voc * 0.9)  # each stem normalised separately
    assert np.abs((i2 + v2) - mix).max() < 1e-3
    assert abs(np.abs(i2).max() - 0.4) < 1e-3 and abs(np.abs(v2).max() - 0.2) < 1e-3


def test_rebalance_trims_to_common_length():
    i2, v2 = rebalance(_sig(1000), _sig(990), _sig(995))
    assert len(i2) == len(v2) == 990


def test_rebalance_avoids_clipping_but_keeps_balance():
    inst, voc = _sig(f=110, amp=0.9), _sig(f=440, amp=0.45)
    i2, v2 = rebalance(inst + voc, inst * 0.5, voc * 0.5)
    assert np.abs(i2).max() <= 0.999 + 1e-6
    assert abs(np.abs(i2).max() / np.abs(v2).max() - 2.0) < 1e-2  # 2:1 balance kept


def test_pick_stems():
    files = [Path("x_(Vocals)_model.wav"), Path("x_(Instrumental)_model.wav")]
    assert pick_stems(files) == (files[1], files[0])
    assert pick_stems([Path("x_(Other)_m.wav")]) == (Path("x_(Other)_m.wav"), None)
    assert pick_stems([Path("x_(Drums)_m.wav")]) == (None, None)


def test_restem_swaps_stems_and_keeps_lyrics(tmp_path, monkeypatch):
    import soundfile as sf

    from karaoke import media, pipeline
    from karaoke.cache import REQUIRED_FILES, Cache

    c = Cache(tmp_path)
    work = c.begin("vid")
    for f in REQUIRED_FILES:
        if f != "meta.json":
            (work / f).write_bytes(b"old")
    (work / "lyrics.lrc").write_text("[00:01.00]keep me")
    c.commit("vid", {"title": "t", "lyrics_mode": "synced", "timings": {}})

    def fake_extract(video, wav):
        sf.write(str(wav), _sig(44100), 44100)

    def fake_separate(wav, out, mode):
        sf.write(str(out / "instrumental.flac"), _sig(44100, 110), 44100)
        sf.write(str(out / "vocals.flac"), _sig(44100, 440), 44100)

    monkeypatch.setattr(media, "extract_audio", fake_extract)
    monkeypatch.setattr(media, "separate", fake_separate)
    meta = pipeline.restem("vid", c)
    d = c.song_dir("vid")
    assert sf.info(str(d / "vocals.flac")).frames == 44100
    assert (d / "lyrics.lrc").read_text() == "[00:01.00]keep me"
    assert meta["lyrics_mode"] == "synced" and meta["separator_model"] == media.SEPARATORS["quality"][0]
    assert c.is_complete("vid") and not (d / ".restem").exists()
