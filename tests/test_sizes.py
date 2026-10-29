"""Multi-size patterns: finding the sizes and splitting them."""

import pytest

from frogless.patterns.sizes import size_count, split_sizes
from frogless.pipeline.check import check_pattern_sizes


def test_stitch_count_brackets():
    parts = split_sizes("sc in next 4 [5, 6] sts")
    assert size_count("sc in next 4 [5, 6] sts") == 3
    assert [t for _, t in parts] == ["sc in next 4 sts", "sc in next 5 sts", "sc in next 6 sts"]


def test_stated_count_inside_parentheses():
    parts = split_sizes("Round 5 (88 [94, 106, 112] sc)")
    assert [t for _, t in parts] == ["Round 5 (88 sc)", "Round 5 (94 sc)", "Round 5 (106 sc)", "Round 5 (112 sc)"]


def test_row_ranges():
    text = "Rows 29-36 [31-38, 31-40]: sc in each st"
    assert size_count(text) == 3
    assert [t for _, t in split_sizes(text)] == [
        "Rows 29-36: sc in each st", "Rows 31-38: sc in each st", "Rows 31-40: sc in each st"]


def test_size_words():
    parts = split_sizes("Small [Medium, Large]: 10 [12, 14] sts")
    assert parts == [("Size 1", "Small: 10 sts"), ("Size 2", "Medium: 12 sts"), ("Size 3", "Large: 14 sts")]


@pytest.mark.parametrize("text", [
    "[sc, inc] 6 times",
    "*[sc, inc] 6 times*",
    "[3dc into ring, ch2]x3",
    "Sl.st [16stitches]",
    "Round 2: sc in each st [12]",
    "Round 3 [sc, 2 sc] around",
    "No brackets at all",
])
def test_repeats_are_not_sizes(text):
    assert size_count(text) == 1
    assert split_sizes(text) == [("Size 1", text)]


def test_label_from_size_line():
    text = "Child's 2 [4, 6, 8]\nRound 1: sc in next 10 [12, 14, 16] sts"
    parts = split_sizes(text)
    assert [label for label, _ in parts] == ["2", "4", "6", "8"]
    assert parts[1][1] == "Child's 4\nRound 1: sc in next 12 sts"


def test_label_falls_back_to_size_numbers():
    parts = split_sizes("Round 1: sc in next 4 [5, 6] sts")
    assert [label for label, _ in parts] == ["Size 1", "Size 2", "Size 3"]


def test_most_common_bracket_length_wins():
    text = "sc in next 4 [5, 6] sts, then 2 [3, 4] sc, then 1 [2, 3, 4] ch"
    parts = split_sizes(text)
    assert len(parts) == 3
    assert parts[1][1] == "sc in next 5 sts, then 3 sc, then 1 [2, 3, 4] ch"


def test_check_pattern_sizes_runs_each_size():
    text = "Round 1: 6 sc in ring (6)\nRound 2: inc in each st around (12 [14, 16])"
    results = check_pattern_sizes(text, use_model=False)
    assert [label for label, _ in results] == ["Size 1", "Size 2", "Size 3"]
    assert [r.stated[2] for _, r in results] == [12, 14, 16]
    assert [r.verdict.kind for _, r in results][0] == "works"


def test_single_size_gives_one_report():
    results = check_pattern_sizes("Round 1: 6 sc in ring (6)", use_model=False)
    assert len(results) == 1 and results[0][1].verdict.kind == "works"



def test_parentheses_sizes_with_size_line():
    text = "Sizes: S (M, L)\nRound 1: sc in next 4 (5, 6) sts\nRound 2: (88 (94, 106) sc)"
    assert size_count(text) == 3
    parts = split_sizes(text)
    assert [lbl for lbl, _ in parts] == ["S", "M", "L"]
    assert parts[1][1] == "Sizes: M\nRound 1: sc in next 5 sts\nRound 2: (94 sc)"


def test_parentheses_finished_size_and_to_fit():
    assert size_count('Finished size: 36 (40, 44)"\nsc in next 4 (5, 6) sts') == 3
    assert size_count("To fit: 2 (4, 6) years\nsc in next 4 (5, 6) sts") == 3


def test_parentheses_value_count_must_match():
    text = "Sizes: S (M, L)\nsc in next 4 (5, 6, 7) sts"
    assert all(t.endswith("sc in next 4 (5, 6, 7) sts") for _, t in split_sizes(text))


def test_repeats_and_groups_without_size_line_not_split():
    for text in ["(sc, inc) 6 times", "(2 dc, ch 2, 2 dc) in next st", "sc in next 4 (5, 6) sts"]:
        assert size_count(text) == 1
    text = "Sizes: S (M, L)\n(sc, inc) 6 times, (2 dc, ch 2, 2 dc) in next st"
    assert all(t.endswith("(sc, inc) 6 times, (2 dc, ch 2, 2 dc) in next st") for _, t in split_sizes(text))


def test_zero_drops_only_that_step():
    text = "Sizes: S (M, L)\nRow 5: sc 3, dec 2 (1, 0) times, sc 2."
    parts = split_sizes(text)
    assert parts[1][1].endswith("Row 5: sc 3, dec 1 times, sc 2.")
    assert parts[2][1] == "Sizes: L\nRow 5: sc 3, sc 2."


def test_zero_rule_repeat_rows_and_last_step():
    text = "Sizes: S (M, L)\nsc 3, dec 2 (1, 0) times.\nRep rows 5-6 0 (2, 4) times."
    parts = split_sizes(text)
    assert parts[2][1] == "Sizes: L\nsc 3.\nRep rows 5-6 4 times."
    assert parts[1][1] == "Sizes: M\nsc 3, dec 1 times.\nRep rows 5-6 2 times."
