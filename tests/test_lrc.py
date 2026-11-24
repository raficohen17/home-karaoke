from karaoke.lrc import Line, best_offset, format_lrc, map_words_to_lines, parse_lrc, plain_lines, shift


def test_parse_basic_and_metadata():
    text = "[ar:Olivia]\n[ti:vampire]\n[00:12.34]Hate to give the satisfaction\n[01:02.5]second\n\n[00:00.00]"
    lines = parse_lrc(text)
    assert lines[0] == Line(0.0, "")
    assert lines[1] == Line(12.34, "Hate to give the satisfaction")
    assert lines[2].t == 62.5


def test_parse_repeated_tags_and_sorting():
    lines = parse_lrc("[00:30.00][00:10.00]chorus\n[00:20.00]verse")
    assert [(line.t, line.text) for line in lines] == [(10.0, "chorus"), (20.0, "verse"), (30.0, "chorus")]


def test_parse_hebrew():
    assert parse_lrc("[00:05.10]שלום, עולם!")[0].text == "שלום, עולם!"


def test_format_roundtrip():
    lines = [Line(5.1, "a"), Line(65.25, "b")]
    assert format_lrc(lines) == "[00:05.10]a\n[01:05.25]b\n"
    assert parse_lrc(format_lrc(lines)) == lines


def test_shift_clamps_at_zero():
    assert shift([Line(1.0, "a"), Line(10.0, "b")], -3) == [Line(0.0, "a"), Line(7.0, "b")]


def test_plain_lines_drops_labels_and_blanks():
    assert plain_lines("[Chorus]\nline one\n\n(Verse 2)\n(x2)\n(פזמון)\n  line two  ") == ["line one", "line two"]


def test_plain_lines_drops_shironet_headers():
    text = "בית א:\nשורה ראשונה\nפזמון:\nפזמון x2:\nבית ב':\nChorus:\nבית שלי: שורה"
    assert plain_lines(text) == ["שורה ראשונה", "בית שלי: שורה"]


def test_plain_lines_keeps_sung_parentheticals():
    assert plain_lines("(מיליון דולר)\n(לא לא לא)\n(Ooh, yeah)") == ["(מיליון דולר)", "(לא לא לא)", "(Ooh, yeah)"]


def test_map_words_to_lines():
    lines = ["one two", "three", "four five six"]
    words = [(1.0, "one"), (1.5, "two"), (3.0, "three"), (5.0, "four"), (5.2, "five"), (5.4, "six")]
    assert map_words_to_lines(lines, words) == [Line(1.0, "one two"), Line(3.0, "three"), Line(5.0, "four five six")]


def test_map_words_drops_lines_without_words():
    assert map_words_to_lines(["a b", "c"], [(1.0, "a"), (2.0, "b")]) == [Line(1.0, "a b")]


def _activity(intervals, length=120.0, hop=0.1):
    n = int(length / hop)
    act = [0.0] * n
    for s, e in intervals:
        for k in range(int(s / hop), int(e / hop)):
            act[k] = 1.0
    return act


def test_best_offset_finds_intro_shift():
    # Album LRC lines at 10, 14, 18, 22; the video has a 7s longer intro.
    lrc_times = [10.0, 14.0, 18.0, 22.0]
    act = _activity([(17.0, 20.5), (21.0, 24.5), (25.0, 28.5), (29.0, 32.5)])
    assert abs(best_offset(lrc_times, act, 0.1) - 7.0) <= 0.3


def test_best_offset_zero_when_aligned():
    lrc_times = [10.0, 14.0, 18.0]
    act = _activity([(10.0, 13.0), (14.0, 17.0), (18.0, 21.0)])
    assert abs(best_offset(lrc_times, act, 0.1)) <= 0.2


def test_best_offset_empty():
    assert best_offset([], [1.0, 1.0], 0.1) == 0.0
