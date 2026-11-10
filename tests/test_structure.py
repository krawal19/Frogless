"""The structure pre-pass: pieces, one round per line, labels with colons, bare counts, prose kept as notes."""

import re

import pytest

from frogless.patterns.structure import split_pieces
from frogless.pipeline.check import check_pattern_pieces, check_pattern_sizes

MULTI = """Jolly Frog

BODY + HEAD - Yarn A
R1 6 sc in MR [6]
R2 inc x6 [12]
R3 (sc, inc) x6 [18] R4 (2 sc, inc) x6 [24]
R5-6 [24]
R7 (2 sc, dec) x6 [18] - stuff firmly
R8 (sc, dec) x6 [12]
R9 dec x6 [6] - stuff, pull closed
Fasten off leaving a long tail

ARMS x2 - Yarn A
R1 6 sc in MR [6]
R2 inc x6 [12]
R3-4 [12]
R5 (sc, dec) x4 [8]
Fasten off leaving a long tail for sewing.

Face plate:
Ch 5
R1 sc in 2nd ch from hook, sc 3 [4]

FEET x2
R1 6 sc in MR [6]
R2 inc x6 [12] R3 (sc, inc) x6 [18] - sew at body R18-19
R4-5 [18]

FINISH
Sew arms to body at R6-7.
"""


def alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def test_a_paste_with_several_pieces_is_split_at_headers():
    pieces = split_pieces(MULTI)
    assert [p.label for p in pieces] == ["BODY + HEAD - Yarn A", "ARMS x2 - Yarn A", "Face plate", "FEET x2"]
    assert pieces[0].text.splitlines()[0] == "R1: 6 sc in MR [6]"
    assert pieces[1].text.splitlines()[0] == "R1: 6 sc in MR [6]"  # row numbers restart


def test_several_rounds_on_one_line_are_split_and_labels_get_colons():
    body = split_pieces(MULTI)[0].text.splitlines()
    assert "R3: (sc, inc) x6 [18]" in body and "R4: (2 sc, inc) x6 [24]" in body
    assert all(re.match(r"R\d+(-\d+)?: ", line) for line in body)


def test_trailing_prose_is_split_off_and_a_round_label_inside_prose_is_not_a_round():
    pieces = split_pieces(MULTI)
    assert "R7: (2 sc, dec) x6 [18]" in pieces[0].text.splitlines()
    assert "stuff firmly" in pieces[0].notes and "stuff, pull closed" in pieces[0].notes
    assert "sew at body R18-19" in pieces[3].notes
    assert not any("R18" in line for line in pieces[3].text.splitlines())


def test_prose_lines_become_notes_not_part_of_a_round():
    pieces = split_pieces(MULTI)
    assert "Fasten off leaving a long tail" in pieces[0].notes
    assert "Fasten off leaving a long tail for sewing." in pieces[1].notes
    assert "FINISH" in pieces[3].notes and "Sew arms to body at R6-7." in pieces[3].notes
    assert not any("Fasten" in p.text or "Sew" in p.text for p in pieces)


def test_bare_count_equal_to_the_round_before_is_read_as_sc_around_and_says_so():
    arms = split_pieces(MULTI)[1]
    assert "R3-4: sc around [12]" in arms.text.splitlines()
    assert any("R3-4 [12]" in r and "sc around" in r for r in arms.readings)


def test_other_bare_counts_are_not_given_stitches():
    piece = split_pieces("R1 [6]\nR2 inc x6 [12]\nR3 [18]")[0]
    assert piece.text.splitlines() == ["R1: [6]", "R2: inc x6 [12]", "R3: [18]"]
    assert len(piece.readings) == 2 and all("nothing was invented" in r for r in piece.readings)


def test_a_label_that_restarts_starts_a_new_piece_without_a_header():
    pieces = split_pieces("R1: 6 sc in MR (6)\nR2: inc x6 (12)\nR1: 6 sc in MR (6)\nR2: inc x6 (12)")
    assert [p.label for p in pieces] == ["Piece 1", "Piece 2"]
    assert pieces[1].text == "R1: 6 sc in MR (6)\nR2: inc x6 (12)"


def test_a_foundation_chain_before_a_restart_goes_with_the_new_piece():
    pieces = split_pieces("R1: 6 sc in MR (6)\nR2: inc x6 (12)\nCh 5.\nR1: sc in 2nd ch from hook, sc 3 (4)")
    assert pieces[0].text == "R1: 6 sc in MR (6)\nR2: inc x6 (12)"
    assert pieces[1].text.splitlines()[0] == "Ch 5."


def test_a_header_that_does_not_restart_the_numbers_is_not_a_new_piece():
    pieces = split_pieces("Body\nR1: 6 sc in MR (6)\nR2: inc x6 (12)\nBrim\nR3: sc around (12)")
    assert len(pieces) == 1 and "Brim" in pieces[0].notes


def test_a_single_piece_that_is_already_in_order_is_unchanged():
    text = "Rnd 1: 6 sc in magic ring (6)\nRnd 2: inc in each st around (12)\nRnd 3: (sc, inc) x6 (18)"
    pieces = split_pieces(text)
    assert len(pieces) == 1 and pieces[0].text == text and not pieces[0].notes and not pieces[0].readings


@pytest.mark.parametrize("text", [MULTI, "R1 6 sc in MR [6] R2 inc x6 [12]\nStuff firmly.\nR3 [12] - sew on front\nFO",
                                   "Intro text only", "Ch 5\nR1 sc in 2nd ch from hook, sc 3 [4]"])
def test_every_input_line_ends_up_as_a_row_a_header_or_a_note(text):
    pieces = split_pieces(text)
    kept = {}
    for piece in pieces:
        for seg in piece.segments:
            assert seg.kind in ("row", "header", "note")
            kept.setdefault(seg.source, []).append(seg.text)
    for line in (l.strip() for l in text.splitlines() if l.strip()):
        assert line in kept, f"{line!r} was dropped"
        # nothing lost from the line: its letters and digits are all still there (a bare count gains "sc around")
        rebuilt = alnum("".join(kept[line]))
        times = [l.strip() for l in text.splitlines()].count(line)  # a line written twice (R1 of two pieces)
        assert alnum(line) * times in (rebuilt, rebuilt.replace("scaround", "", 1)), line
    texts = [t for ts in kept.values() for t in ts]
    rows = [seg.text for p in pieces for seg in p.segments if seg.kind == "row"]
    assert all(r in "\n".join(p.text for p in pieces) for r in rows)
    assert len(texts) >= len(kept)


def test_pieces_are_checked_on_their_own_and_return_one_result_each():
    results = check_pattern_pieces(MULTI, use_model=False)
    assert [label for label, _ in results] == ["BODY + HEAD - Yarn A", "ARMS x2 - Yarn A", "Face plate", "FEET x2"]
    by = {label: r for label, r in results}
    arms = by["ARMS x2 - Yarn A"]
    assert arms.verdict.kind == "works" and arms.stated[1] == 6  # row numbers restarted
    assert any("R3-4 [12]" in n for n in arms.notes)
    assert "Fasten off leaving a long tail for sewing." in arms.prose
    assert by["FEET x2"].verdict.kind == "works"


def test_a_single_piece_gives_one_result_labelled_like_a_size():
    results = check_pattern_sizes("Round 1: 6 sc in ring (6)\nRound 2: inc in each st around (12)", use_model=False)
    assert [label for label, _ in results] == ["Size 1"] and results[0][1].verdict.kind == "works"


def test_sizes_and_pieces_combine():
    text = ("Sizes: S (M)\nBody\nR1: 6 sc in MR (6)\nR2: inc x6 (12 [14, 16])\nArms\nR1: 6 sc in MR (6)\nR2: inc x6 (12 [14, 16])")
    labels = [label for label, _ in check_pattern_sizes(text, use_model=False)]
    assert len(labels) == 6 and all(": " in label for label in labels)


def test_uk_terms_stated_in_a_prose_line_still_count():
    text = "UK terms\nBody\nR1: 6 dc in MR (6)\nR2: 2 dc in each st around (12)\nArms\nR1: 6 dc in MR (6)"
    for _, report in check_pattern_pieces(text, use_model=False):
        assert report.terms.kind == "UK"


def test_a_bare_stitch_with_a_count_equal_to_the_round_before_is_read_as_around_and_says_so():
    piece = split_pieces("R1 6 sc in MR [6]\nR2 inc x6 [12]\nR3-4 sc [12]\nR5 sc [18]")[0]
    assert piece.text.splitlines()[2:] == ["R3-4: sc around [12]", "R5: sc [18]"]  # only when equal
    assert len(piece.readings) == 1 and "R3-4 sc [12]" in piece.readings[0]


def test_a_bare_first_round_reuses_an_earlier_pieces_first_round_with_the_same_count():
    text = "BODY\nR1 6 sc in MR [6]\nR2 inc x6 [12]\n\nARMS x2\nR1 [6]\nR2 (sc, inc) x3 [9]\n\nLEGS\nR1 [8]\nR2 inc x8 [16]"
    pieces = split_pieces(text)
    assert pieces[1].text.splitlines()[0] == "R1: 6 sc in MR [6]"
    assert "'R1 [6]' as R1 of 'BODY'" in pieces[1].readings[0]
    assert pieces[2].text.splitlines()[0] == "R1: [8]" and "nothing was invented" in pieces[2].readings[0]


def test_a_header_with_a_comma_and_a_title_before_it():
    pieces = split_pieces("JOLLY crochet pattern\n\nBODY + HEAD — Yarn A, top-down\nR1 6 sc in MR [6]\nR2 inc x6 [12]")
    assert pieces[0].label == "BODY + HEAD — Yarn A, top-down" and pieces[0].notes == ["JOLLY crochet pattern"]
    assert pieces[0].text.splitlines()[0] == "R1: 6 sc in MR [6]"


def test_prose_after_the_count_of_an_unlabelled_continuation_line_is_split_off():
    piece = split_pieces("Ch 5\nR1 sc in 2nd ch from hook,\nsc 3 [4] — sew on front")[0]
    assert piece.text.splitlines()[-1] == "sc 3 [4]" and piece.notes == ["sew on front"]
