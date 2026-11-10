"""Common wordings the rules translator misreads are written out plainly; look-alikes are left as written."""

import pytest

from frogless.patterns.wording import normalise_wording
from frogless.pipeline.check import check_pattern

RING = "Rnd 1: 6 sc in magic ring (6)\nRnd 2: inc in each st around (12)\n"
FLAT = ("Ch 9.\nR1: sc in 2nd ch from hook and in each ch across, turn (8)\n"
        "R2: ch 1, sc in each st across, turn (8)\nR3: ch 1, sc in each st across, turn (8)\n")
ROW = "ch 1, sc in each st across, turn (8)"


def norm(text: str) -> str:
    return normalise_wording(text)[0]


@pytest.mark.parametrize("written", [
    "*sc, inc* around (18)",
    "*sc, inc; rep from * around (18)",
    "*sc, inc, rep from * around (18)",
    "*sc, inc* rep around (18)",
    "*sc, inc* repeat from * around (18)",
    "*sc, inc; repeat from * around (18)",
])
def test_asterisk_around_forms_become_a_counted_repeat(written):
    assert norm(RING + "Rnd 3: " + written) == RING + "Rnd 3: (sc, inc) 6 times (18)"


def test_asterisk_around_without_a_stated_count_and_with_an_equals_count():
    assert norm(RING + "Rnd 3: *sc, inc* around") == RING + "Rnd 3: (sc, inc) 6 times"
    assert norm(RING + "Rnd 3: *sc, inc* around = 18") == RING + "Rnd 3: (sc, inc) 6 times = 18"


def test_the_times_come_from_the_stitches_each_repeat_works_into():
    assert norm(RING + "Rnd 3: *sc in next 3 sts, inc; rep from * around (15)").endswith(
        "Rnd 3: (sc in next 3 sts, inc) 3 times (15)")
    assert norm(RING + "Rnd 3: *dec; rep from * around (6)").endswith("Rnd 3: (dec) 6 times (6)")
    assert norm(RING + "Rnd 3: *2 sc, dec* around").endswith("Rnd 3: (2 sc, dec) 3 times")
    assert norm("Rnd 1: 12 dc in magic ring = 12\nRnd 2: *dc, dc inc; rep from * around = 18").endswith(
        "Rnd 2: (dc, dc inc) 6 times = 18")


def test_inc_around_and_dec_around():
    assert norm("Rnd 1: 6 sc in magic ring (6)\nRnd 2: inc around (12)") == (
        "Rnd 1: 6 sc in magic ring (6)\nRnd 2: inc in each st around (12)")
    assert norm(RING + "Rnd 3: dec around (6)") == RING + "Rnd 3: (dec) 6 times (6)"
    assert norm(RING + "Rnd 3: sc2tog around") == RING + "Rnd 3: (sc2tog) 6 times"


def test_asterisk_repeat_with_the_times_stated():
    assert norm("Rnd 3: *sc, inc* x 6 = 18") == "Rnd 3: (sc, inc) x 6 = 18"
    assert norm("Rnd 3: *sc, inc* 6 times (18)") == "Rnd 3: (sc, inc) 6 times (18)"


@pytest.mark.parametrize("text", [
    "Rnd 1: 7 sc in magic ring (7)\nRnd 2: *sc, inc* around",              # 7 is not whole repeats of 2
    RING + "Rnd 3: *sc, inc* around (20)",                                  # the stated count disagrees
    "Rnd 3: *sc, inc* around (18)",                                         # nothing before it: no count to go by
    "Rnd 1: 6 sc in magic ring\nRnd 2: *sc, inc* around",                   # the round before states no count
    RING + "Rnd 4: *sc, inc* around (18)",                                  # not the round right after
    RING + "Rnds 3-4: *sc, inc* around",                                    # a range of rounds
    RING + "Rnd 3: ch 1, *sc, inc* around (19)",                            # something before the repeat
    RING + "Rnd 3: *sc, ch 1, inc* around (18)",                            # an instruction that is not plain
    RING + "Rnd 3: *sc, (inc, sc)* around (18)",                            # nested brackets
    RING + "Rnd 3: *sc, inc* around, sl st to join",                        # more after "around"
    RING + "Rnd 3: *sc, inc* to end (18)",                                  # "to end" is not "around"
    RING + "Rnd 3: *sc, inc; rep from * 5 times (18)",                      # "rep from * N times": total unclear
    "Rnd 1: 6 sc in magic ring (6)\nRnd 2: 7 sc (7)\nRnd 3: dec around",    # odd count cannot be all decreases
    RING + "Rnd 3: dec around (5)",                                         # stated count disagrees
    RING + "Rnd 3: sc, inc around",                                         # no asterisks or brackets: unclear
])
def test_look_alikes_are_left_as_written(text):
    assert norm(text) == text


def test_repeat_rows_written_out():
    text = FLAT + "Repeat rows 2 and 3 three more times.\nR10: " + ROW
    out, notes = normalise_wording(text)
    assert out == FLAT + "\n".join(f"R{n}: {ROW}" for n in range(4, 11))
    assert notes == ["wrote out 'Repeat rows 2 and 3 three more times.' as rows 4-9 (the rows it repeats, again) before checking"]


def test_repeat_rows_other_spellings():
    assert norm(FLAT + "Rep rows 2-3 twice more.") == FLAT + "\n".join(f"R{n}: {ROW}" for n in range(4, 8))
    assert norm(FLAT + "Repeat Rows 2 & 3 once more") == FLAT + "\n".join(f"R{n}: {ROW}" for n in (4, 5))
    same_line = FLAT.rstrip("\n") + ". Repeat rows 2 and 3 once more."
    assert norm(same_line) == FLAT + "\n".join(f"R{n}: {ROW}" for n in (4, 5))


def test_repeat_rows_alternate_the_rows_in_a_labelled_range():
    flat = FLAT.replace(f"R3: {ROW}", "R3: ch 1, sc in each st across, turn (8) [bump]")
    rows = norm(flat + "R4-7: Repeat R2 and R3").split("\n")[-4:]
    assert rows == [f"R4: {ROW}", "R5: ch 1, sc in each st across, turn (8) [bump]", f"R6: {ROW}",
                    "R7: ch 1, sc in each st across, turn (8) [bump]"]


@pytest.mark.parametrize("tail", [
    "Repeat rows 2 and 3 until piece measures 6 inches.",     # no count to write out
    "Repeat rows 2 and 3 four times.",                         # four more, or four in all
    "Repeat rows 2 and 3 three more times.\nR9: " + ROW,       # the next row's number does not fit
    "Repeat rows 1 and 3 once more.",                           # not consecutive rows
    "Repeat rows 1 and 2 once more.",                           # not the rows just above
    "R4-8: Repeat R2 and R3",                                   # five rows is not whole repeats of two
    "R5-6: Repeat R2 and R3",                                   # does not start right after the repeated rows
])
def test_row_repeats_that_are_not_clear_are_left_as_written(tail):
    assert norm(FLAT + tail) == FLAT + tail


def test_a_section_header_glued_to_the_row_before_goes_on_its_own_line():
    row4 = f"R4: {ROW}"
    assert norm(FLAT + row4 + " Edging: Round 1: sc around (20)") == FLAT + row4 + "\nEdging:\nRound 1: sc around (20)"
    assert norm(FLAT + row4 + "\nEdging: Round 1: sc around (20)") == FLAT + row4 + "\nEdging:\nRound 1: sc around (20)"
    assert norm("Left ear: Round 1: 6 sc in ring (6)") == "Left ear:\nRound 1: 6 sc in ring (6)"


@pytest.mark.parametrize("text", [
    "Rnd 3: Rnd 4: sc",                       # labels are not headers
    "Make 2: Round 1: 6 sc in ring (6)",       # a number is not a header word
    "Edging: sc around",                        # an instruction after the header: not split
    "Note: edging is optional.",                # no row after it
])
def test_other_colons_are_left_alone(text):
    assert norm(text) == text


def test_end_to_end_no_model():
    r = check_pattern(RING + "Rnd 3: *sc, inc; rep from * around (18)", use_model=False, terms="US")
    assert r.verdict.kind == "works"
    assert all(row.status == "ok" for row in r.rows)
    assert r.text.endswith("*sc, inc; rep from * around (18)")  # the report keeps what was written
    r = check_pattern(FLAT + "Repeat rows 2 and 3 once more.", use_model=False, terms="US")
    assert r.verdict.kind == "works"
    assert sum("ch 1, sc in each st" in row.source for row in r.rows) == 4
    assert any("wrote out" in n for n in r.notes)
    r = check_pattern(RING + "Rnd 3: *sc, inc* around (20)", use_model=False, terms="US")
    assert r.verdict.kind != "works"  # a wrong stated count is still caught
