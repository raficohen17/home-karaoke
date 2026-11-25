from karaoke import ctc_align as c

EN = {"-": 0, "a": 1, "b": 2, "'": 3, "*": 4}
HE = {"<pad>": 0, "א": 1, "ב": 2, "ת": 3}


def test_english_tokens_keep_letters_and_apostrophe():
    assert c.english_tokens("Ab’", EN) == [1, 2, 3]
    assert c.english_tokens("22,", EN) == []
    assert c.english_tokens("a*", EN) == [1]  # vocab symbols that are not letters are never emitted


def test_hebrew_tokens_drop_niqqud_and_punctuation():
    assert c.hebrew_tokens("אַבָּא,", HE) == [1, 2, 1]
    assert c.hebrew_tokens("(בת)", HE) == [2, 3]


def test_chunk_plan_frames_line_up_end_to_end():
    sr, hop = c.SR, c.HOP
    n = 75 * sr
    plan = c.chunk_plan(n)
    assert len(plan) == 3
    assert plan[0][0] == 0 and plan[0][2] == 0  # first chunk has no left context
    assert plan[1][0] == 29 * sr and plan[1][2] == sr // hop  # 1s of left context skipped
    assert sum(f1 - f0 for _, _, f0, f1 in plan) == n // hop
    assert plan[-1][1] == n


def test_word_starts_maps_spans_back_to_words():
    spans = [(10, 0.9), (12, 0.7), (50, 0.5)]
    words = [("ab", [1, 2]), ("22", []), ("a", [1])]
    assert c.word_starts(spans, words, 0.02) == [(0.2, "ab", 0.8), (1.0, "a", 0.5)]
