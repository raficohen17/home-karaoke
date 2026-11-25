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


def test_map_words_survives_merged_tokens():
    # stable-ts merged "-" with the next word on פנתרה; token counting then shifted every later line
    lines = ["עם שיניים חשופות - נושכת", "בוא תביא לי", "אני פנתרה"]
    words = [(1.0, "עם"), (1.4, "שיניים"), (1.9, "חשופות"), (2.4, "- נושכת"), (5.0, "בוא"), (5.3, "תביא"),
             (5.6, "לי"), (8.0, "אני"), (8.4, "פנתרה")]
    assert map_words_to_lines(lines, words) == [Line(1.0, lines[0]), Line(5.0, lines[1]), Line(8.0, lines[2])]


def test_map_words_survives_split_tokens_and_punctuation():
    lines = ["la-la-la, yeah", "don't stop", "(ooh)"]
    words = [(1.0, "la"), (1.2, "-la"), (1.4, "-la,"), (1.8, "yeah"), (3.0, "don"), (3.1, "'t"), (3.3, "stop"),
             (4.0, "("), (4.1, "ooh)")]
    assert map_words_to_lines(lines, words) == [Line(1.0, lines[0]), Line(3.0, lines[1]), Line(4.1, lines[2])]


def test_map_words_repeated_lines_get_their_own_times():
    lines = ["אני פנתרה", "אני פנתרה"]
    words = [(10.0, "אני"), (10.5, "פנתרה"), (20.0, "אני"), (20.5, "פנתרה")]
    assert [l.t for l in map_words_to_lines(lines, words)] == [10.0, 20.0]


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


# ---------- word-level timing ----------
from karaoke.lrc import anchor_words, interpolate, monotonic_anchors  # noqa: E402


def test_enhanced_lrc_roundtrip():
    lines = [Line(1.0, "one two", ((1.0, "one"), (1.5, "two"))), Line(4.0, "plain line")]
    text = format_lrc(lines)
    assert text == "[00:01.00]<00:01.00>one <00:01.50>two\n[00:04.00]plain line\n"
    assert parse_lrc(text) == lines


def test_shift_moves_word_times():
    (line,) = shift([Line(5.0, "a b", ((5.0, "a"), (5.4, "b")))], -0.3)
    assert line.t == 4.7 and line.words == ((4.7, "a"), (5.1000000000000005, "b")) or abs(line.words[1][0] - 5.1) < 1e-9


def test_monotonic_anchors_drops_outliers():
    pts = [(0, 1.0), (10, 2.0), (20, 50.0), (30, 3.0), (40, 4.0), (50, 0.5)]
    assert monotonic_anchors(pts) == [(0, 1.0), (10, 2.0), (30, 3.0), (40, 4.0)]


def test_interpolate_between_and_outside():
    a = [(10, 2.0), (20, 4.0)]
    assert interpolate(a, 15) == 3.0
    assert interpolate(a, 0) == 0.0  # 10 chars before at 0.2 s/char, clamped at 0
    assert interpolate(a, 30) == 6.0


def test_anchor_words_ignores_low_confidence_and_fills_gaps():
    lines = ["one two three", "four five six"]
    words = [  # "two" is misplaced with low confidence; "five" is way off with high confidence
        (1.0, "one", 0.9), (9.0, "two", 0.1), (2.0, "three", 0.8),
        (4.0, "four", 0.9), (40.0, "five", 0.9), (6.0, "six", 0.9),
    ]
    out = anchor_words(lines, words)
    assert [l.t for l in out] == [1.0, 4.0]
    w = dict((tok, t) for l in out for t, tok in l.words)
    assert 1.0 < w["two"] < 2.0  # placed between its confident neighbours, not at 9.0
    assert 4.0 < w["five"] < 6.0  # outlier rejected by monotonicity
    assert all(l.words for l in out)


def test_anchor_words_times_a_line_with_no_confident_words():
    lines = ["aaa", "bbb", "ccc"]
    out = anchor_words(lines, [(1.0, "aaa", 0.9), (99.0, "bbb", 0.1), (3.0, "ccc", 0.9)])
    assert [l.text for l in out] == lines and abs(out[1].t - 2.0) < 1e-6


def test_anchor_words_needs_two_anchors():
    assert anchor_words(["a b"], [(1.0, "a", 0.9), (2.0, "b", 0.2)]) == []


from karaoke.lrc import words_in_synced  # noqa: E402


def test_words_in_synced_keeps_line_starts_and_times_words():
    lines = [Line(10.0, "aa bb cc"), Line(20.0, "dd ee")]
    words = [(10.2, "aa", 0.9), (11.0, "bb", 0.9), (12.0, "cc", 0.9), (20.1, "dd", 0.9), (21.0, "ee", 0.9)]
    out = words_in_synced(lines, words)
    assert [l.t for l in out] == [10.0, 20.0]
    assert [t for t, _ in out[0].words] == [10.0, 11.0, 12.0]  # first word never before or after its line start
    assert [w for _, w in out[1].words] == ["dd", "ee"]
    assert out[1].words[1][0] == 21.0


def test_words_in_synced_ignores_words_outside_their_line():
    lines = [Line(10.0, "aa bb"), Line(20.0, "cc dd")]
    # "bb" aligned into the next line's window: not trusted, interpolated inside line 1 instead
    words = [(10.0, "aa", 0.9), (25.0, "bb", 0.9), (20.0, "cc", 0.9), (21.0, "dd", 0.9)]
    out = words_in_synced(lines, words)
    assert 10.0 < out[0].words[1][0] < 20.0


def test_words_in_synced_spreads_unaligned_line_within_its_window():
    lines = [Line(10.0, "aa bb"), Line(12.0, "cc dd ee ff gg hh ii jj"), Line(14.0, "kk ll")]
    words = [(10.0, "aa", 0.9), (10.5, "bb", 0.9), (14.0, "kk", 0.9), (14.5, "ll", 0.9)]
    out = words_in_synced(lines, words, min_coverage=0.0)
    ts = [t for t, _ in out[1].words]
    assert ts[0] == 12.0 and ts == sorted(ts) and ts[-1] < 14.0


def test_words_in_synced_gates_on_coverage():
    lines = [Line(1.0, "aa bb cc dd"), Line(5.0, "ee ff gg hh")]
    stats: dict = {}
    out = words_in_synced(lines, [(1.0, "aa", 0.9)], stats=stats)
    assert out == lines and stats["coverage"] < 0.35


def test_words_in_synced_repeated_lines_each_get_words():
    lines = [Line(10.0, "la la"), Line(20.0, "la la")]
    words = [(10.0, "la", 0.9), (10.5, "la", 0.9), (20.0, "la", 0.9), (20.6, "la", 0.9)]
    out = words_in_synced(lines, words)
    assert [t for t, _ in out[1].words] == [20.0, 20.6]
