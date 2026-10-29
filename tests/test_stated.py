"""Stated-count reader and the stated-count gate."""

import pytest

from frogless.engine import TranslateLine, TranslateResult, get_engine
from frogless.patterns.stated import StatedCount, stated_count
from frogless.pipeline.gate import gate_translation


@pytest.mark.parametrize("line, count, stitch", [
    ("Row 2: sc in each st (12)", 12, None),
    ("Rnd 3: (sc, inc) x 6 (18 sts)", 18, None),
    ("Rnd 3: (sc, inc) x 6 (18 sc)", 18, "sc"),
    ("Row 2: sc across, ch 1, turn = 10", 10, None),
    ("Row 2: sc across, ch 1, turn = 10.", 10, None),
    ("Row 2: dc across = 14 dc", 14, "dc"),
    ("Rnd 4: sc around: 14 sc", 14, "sc"),
    ("Rnd 4: sc around — 14 sc", 14, "sc"),
    ("Rnd 4: sc around - 14 sc", 14, "sc"),
    ("Row 5: dc across [12dc]", 12, "dc"),
    ("Row 5: dc across [16stitches]", 16, None),
    ("Row 5: dc across [64 stitches]", 64, None),
    ("Rnd 6: sc around. (There are 14 sc in this round)", 14, "sc"),
    ("Row 7: dc in each st, 12 dc in total", 12, "dc"),
    ("Row 2: sc across (12), ch 1, turn", 12, None),
])
def test_stated_counts(line, count, stitch):
    assert stated_count(line) == StatedCount(count, stitch)


def test_multi_size_takes_first_number():
    got = stated_count("Row 3: sc across (88 [94, 106] sc)")
    assert got == StatedCount(88, "sc", multi_size=True)


@pytest.mark.parametrize("line", [
    "Row 1: (2 dc, ch 2, 2 dc) in next sp",
    "Rnd 2: (sc, inc) x 6",
    "Rnd 2: [sc, inc] 6 times",
    "Row 1: ch 2 (counts as dc), dc in next st",
    "Rnd 1: 6 sc in magic ring",
    "Rnd 1: 6 sc",
    "Rows 2-5: sc across",
    "Ch 11",
    "Fasten off.",
    "",
])
def test_instructions_are_not_counts(line):
    assert stated_count(line) is None


def test_gate_flags_rows_that_miss_their_stated_count():
    engine = get_engine()
    text = ("Ch 11. Row 1: sc in 2nd ch from hook and across, ch 1, turn = 10. "
            "Row 2: sc across, ch 1, turn = 10")
    gated = gate_translation(engine, engine.translate(text), text)
    rows = [l for l in gated.lines if "row" in l.source]
    assert len(rows) == 2
    for line in rows:  # both are unreadable or wrongly read by the rules; neither may pass as parsed
        assert not line.parsed and not line.code
    assert any(l.reason.startswith("stated count 10, translation makes") for l in rows)
    assert gated.lines[0].parsed  # the chain row stays


def test_gate_keeps_correct_lines_and_skips_lines_without_counts():
    engine = get_engine()
    text = "Rnd 1: 6 sc in magic ring (6)\nRnd 2: 2 sc in each st around (12)\nRnd 3: sc around"
    plain = engine.translate(text)
    gated = gate_translation(engine, plain, text)
    assert plain.all_parsed
    assert [l.parsed for l in gated.lines] == [l.parsed for l in plain.lines]


def test_gate_flags_wrong_count_with_reason():
    engine = get_engine()
    lines = [TranslateLine("ch 11", "11ch", True),
             TranslateLine("row 1: sc across, ch 1, turn = 10", "10sc", True),
             TranslateLine("row 2: sc in each st (9)", "10sc", True)]
    out = gate_translation(engine, TranslateResult(lines), "")
    assert [l.parsed for l in out.lines] == [True, True, False]
    assert out.lines[2].reason == "stated count 9, translation makes 10"
    assert out.lines[2].code == ""


def test_gate_counts_only_the_stated_type():
    engine = get_engine()
    lines = [TranslateLine("ch 6", "6ch", True), TranslateLine("row 1: 5 sc (5 sc)", "5sc", True),
             TranslateLine("row 2: 5 dc (4 dc)", "5dc", True)]
    out = gate_translation(engine, TranslateResult(lines), "")
    assert [l.parsed for l in out.lines] == [True, True, False]


def test_gate_leaves_unparsed_and_synthetic_lines_alone():
    engine = get_engine()
    lines = [TranslateLine("magic", "", False, "x"), TranslateLine("make a magic ring.", "ring", True, synthetic=True)]
    out = gate_translation(engine, TranslateResult(lines), "")
    assert out.lines == lines


def _graph_row(kinds):
    from frogless.engine import RowInfo, StitchInfo

    types = {}
    for k in kinds:
        types[k] = types.get(k, 0) + 1
    return RowInfo(1, len(kinds), types, stitches=[StitchInfo(i, k) for i, k in enumerate(kinds)])


def test_bare_count_counts_every_chain_but_the_turning_chain():
    from frogless.pipeline.gate import row_counts

    granny = _graph_row(["ch", "ch", "ch"] + ["dc", "dc", "ch", "ch", "dc", "dc"] * 2)  # ch 3 turning + 2 corners
    assert row_counts(granny, None) == [12, 8]  # 8 dc + 4 corner chains; the fallback leaves all chains out
    assert row_counts(granny, "dc") == [8]  # "(8 dc)" counts dc only


def test_all_chains_left_out_is_the_fallback_reading():
    from frogless.pipeline.gate import row_counts

    row = _graph_row(["ch"] + ["sc", "ch"] * 4 + ["sc"])  # turning chain, 5 sc, 4 mesh chains
    assert row_counts(row, None) == [9, 5]  # mesh chains count; leaving every chain out is second
    assert row_counts(row, "sc") == [5]


def test_without_the_stitch_graph_chains_are_taken_as_the_turning_chain():
    from types import SimpleNamespace

    from frogless.pipeline.gate import row_counts

    row = SimpleNamespace(stitch_count=15, stitch_types={"dc": 12, "ch": 3})
    assert row_counts(row, None) == [12, 12]


def test_a_join_before_the_turning_chain_is_passed_over():
    from frogless.pipeline.gate import leading_chains

    assert leading_chains(_graph_row(["ss", "ch", "ch", "dc"])) == 2
    assert leading_chains(_graph_row(["dc", "ch", "dc"])) == 0


def test_what_a_line_says_about_its_turning_chain():
    from frogless.patterns.stated import turning_chain_says as says

    assert says("Row 2: ch 3 (counts as first dc), dc across") is True
    assert says("Row 2: ch 2 (counts as a st), hdc in each st") is True
    assert says("Rnd 2: ch 5 (counts as dc + ch 2), dc in next st") is True
    assert says("Row 2: ch 3 (does not count as a st), dc across") is False
    assert says("Row 2: ch 3 doesn't count as dc, dc across") is False
    assert says("Row 2: ch 3, dc across") is None
    assert says("Rnd 3: 6 sc counts as one repeat") is None  # nothing about a chain


def test_counts_of_special_stitches_are_typed_counts():
    for text, kind in [("Rnd 3: ... (6 popcorns)", "pc"), ("Rnd 3: ... (12 pc)", "pc"), ("= 5 popcorn sts", "pc"),
                       ("Rnd 3: ... (8 bobbles)", "bobble"), ("Rnd 3: ... [8bobble sts]", "bobble"),
                       ("Rnd 3: ... (6 puff sts)", "puff"), ("Rnd 3: ... (6 puffs)", "puff")]:
        found = stated_count(text)
        assert found is not None and found.stitch == kind, text
    assert stated_count("Rnd 3: ... (6 popcorns)").count == 6
    assert stated_count("Rnd 3: ... (12 sts)").stitch is None  # all stitches, not a special one


def test_a_special_stitch_count_counts_only_that_stitch():
    from frogless.engine import RowInfo
    from frogless.pipeline.gate import row_counts

    row = RowInfo(2, 18, {"dc5pc": 6, "dc": 6, "a dc bobble of 3 stitches": 4, "an hdc puff of 3 stitches": 2})
    assert row_counts(row, "pc") == [6]
    assert row_counts(row, "bobble") == [4]
    assert row_counts(row, "puff") == [2]
    assert row_counts(row, "dc") == [12]  # as before: "dc" covers the dc variants the engine names


def test_wording_clues_about_the_turning_chain():
    from frogless.patterns.stated import (
        turning_chain_clue, turning_chain_hint, turning_chain_says, turning_chain_stated)

    assert turning_chain_says("Row 2: ch 3, dc in next st, dc across") is True  # starts in the NEXT st: chain counts
    assert turning_chain_says("Row 2: ch 3, dc in first st, dc across") is False
    assert turning_chain_says("Row 2: ch 3, dc in same st, dc across") is False
    assert turning_chain_says("Row 2: ch 3, dc in each st across") is None
    assert turning_chain_says("Row 2: ch 2, sc in the first ch 1 space") is None  # a space, not a stitch
    # a last stitch worked into the previous row's turning chain
    for text in ("Row 2: dc across, dc in top of turning ch", "Row 3: last dc in 3rd ch of beg ch-3",
                 "Row 2: sk 1, dc in 2nd ch of turning ch, turn", "Row 2: dc across, dc in top of ch-3"):
        assert turning_chain_says(text) is True, text
    assert turning_chain_clue("Row 2: ch 3, dc in first st, dc in top of turning ch") is None  # says both
    # an explicit statement beats a clue on the same line and in the pattern as a whole
    assert turning_chain_says("Row 2: ch 3 (does not count), dc in next st") is False
    assert turning_chain_says("Row 2: ch 3 (counts as dc), dc in first st") is True
    rows = ["Row 2: ch 2, sk 1, dc in 2nd ch of turning ch, turn.",
            "Notes: turning ch 2 does not count as a stitch unless stated otherwise."]
    assert turning_chain_stated(rows) is False and turning_chain_hint(rows) is None
    assert turning_chain_stated(rows[:1]) is None and turning_chain_hint(rows[:1]) is True
