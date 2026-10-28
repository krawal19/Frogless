"""code -> English. Unit cases per construct, plus an English -> code -> English -> code round trip.

These run the real engine through Node, so Node must be installed.
"""

import pytest

from frogless.engine import get_engine

E = get_engine()


def describe(code):
    return E.describe(code)


# ---------------------------------------------------------------- unit cases
def test_magic_ring_and_first_round():
    assert describe("ring.R0\n(6sc)@R0") == ["Make a magic ring.", "Round 1: 6 sc in magic ring."]


def test_ring_round_with_chain_first():
    assert describe("ring.R0\n2ch,(8dc)@R0") == ["Make a magic ring.", "Round 1: ch 2, 8 dc in magic ring."]


@pytest.mark.parametrize(
    "stitch,word",
    [("sc", "sc"), ("hdc", "hdc"), ("dc", "dc"), ("tr", "tr"), ("dtr", "dtr"), ("trtr", "trtr")],
)
def test_plain_stitches(stitch, word):
    assert describe(f"ring.R0\n(6sc)@R0\n6{stitch}")[-1] == f"Round 2: {word} in next 6 sts."
    assert describe(f"ring.R0\n(6sc)@R0\n5{stitch},{stitch}")[-1] == (
        f"Round 2: {word} in next 5 sts, {word} in next st."
    )


def test_chain_and_slip_stitch():
    out = describe("ring.R0\n(6sc)@R0\n6sc,2ch,ss")
    assert out[-1] == "Round 2: sc in next 6 sts, ch 2, join with sl st to first st."
    assert describe("ring.R0\n(6sc)@R0\n6sc,ch")[-1] == "Round 2: sc in next 6 sts, ch 1."


def test_trailing_ss_in_a_round_is_the_join_but_not_in_the_middle():
    assert describe("ring.R0\n(6sc)@R0\n6sc,ss")[-1] == "Round 2: sc in next 6 sts, join with sl st to first st."
    assert describe("ring.R0\n(6sc)@R0\n3sc,ss,3sc")[-1] == "Round 2: sc in next 3 sts, ss in next st, sc in next 3 sts."


def test_ss_to_first_stitch_closes_round():
    assert describe("ring.R0\n(6sc)@R0\n6sc,ss@[%,0]")[-1] == "Round 2: sc in next 6 sts, ss to first st."


def test_increase():
    assert describe("ring.R0\n(6sc)@R0\n6*[sc2inc]")[-1] == "Round 2: (2 sc in next st) 6 times."
    assert describe("ring.R0\n(6dc)@R0\n6*[dc3inc]")[-1] == "Round 2: (3 dc in next st) 6 times."
    assert describe("ring.R0\n(6hdc)@R0\nhdc2inc,5hdc")[-1] == "Round 2: 2 hdc in next st, hdc in next 5 sts."


def test_decrease():
    out = describe("ring.R0\n(6sc)@R0\n6*[sc2inc]\n4*[2sc,sc2tog]")
    assert out[-1] == "Round 3: (sc in next 2 sts, sc2tog) 4 times."
    assert describe("ring.R0\n(6sc)@R0\n3*[dc3tog]")[-1] == "Round 2: (dc3tog) 3 times."
    assert describe("ring.R0\n(6sc)@R0\nsc2tog,4sc")[-1] == "Round 2: sc2tog, sc in next 4 sts."


def test_repeats():
    assert describe("ring.R0\n(6sc)@R0\n3*[sc,sc2inc]")[-1] == "Round 2: (sc in next st, 2 sc in next st) 3 times."
    assert describe("ring.R0\n(6sc)@R0\n[sc,sc2inc]*3")[-1] == describe("ring.R0\n(6sc)@R0\n3*[sc,sc2inc]")[-1]
    assert describe("ring.R0\n(6sc)@R0\n1*[sc,sc2inc]")[-1].endswith("1 time.")
    # a repeated single plain stitch is just that many stitches
    assert describe("ring.R0\n(6sc)@R0\n3*[2*[sc],sc2inc]")[-1] == (
        "Round 2: (sc in next 2 sts, 2 sc in next st) 3 times."
    )


def test_skip():
    assert describe("ring.R0\n(6sc)@R0\n4sc,2ch,2sk")[-1] == "Round 2: sc in next 4 sts, ch 2, skip 2."


def test_rows_with_foundation_chain_and_turn():
    out = describe("11ch\n10sc,turn\nch,10sc,turn\n3ch,10dc")
    assert out == [
        "Ch 11.",
        "Row 1: sc in 2nd ch from hook and in each ch across, turn.",
        "Row 2: ch 1, sc in next 10 sts, turn.",
        "Row 3: ch 3, dc in next 10 sts.",
    ]


def test_fasten_off():
    assert describe("ring.R0\n(6sc)@R0\ntie_up")[-1] == "Fasten off."


RING = "ring.R0\n(6sc)@R0\n"


def last(code):
    return describe(code)[-1]


def test_labels_on_stitches_and_spaces():
    assert last(RING + "3sc,sc.A,2sc") == "Round 2: sc in next 3 sts, sc in next st (mark this st as A), sc in next 2 sts."
    assert last(RING + "tr.A") == "Round 2: tr in next st (mark this st as A)."
    assert last(RING + "dc.S") == "Round 2: dc in next st (mark this st as S)."
    assert last(RING + "5ch.L") == "Round 2: ch 5 (mark this space as L)."
    assert last(RING + "2ch.B") == "Round 2: ch 2 (mark this space as B)."
    assert last(RING + "3dc.S") == "Round 2: dc in next 3 sts (mark these 3 sts as S)."
    assert last(RING + "sc.A.B") == "Round 2: sc in next st (mark this st as A and B)."
    assert last(RING + "dc2inc.A") == "Round 2: 2 dc in next st (mark this st as A)."


def test_single_attachments():
    assert last(RING + "dc.S,ss@S") == "Round 2: dc in next st (mark this st as S), ss to marked st S."
    assert last(RING + "2ch.A,ss@A") == "Round 2: ch 2 (mark this space as A), ss to marked space A."
    assert last(RING + "3dc.S,2dc,3dc@S") == (
        "Round 2: dc in next 3 sts (mark these 3 sts as S), dc in next 2 sts, dc in each of the 3 marked sts S."
    )
    assert last(RING + "dc.S,3dc@S") == "Round 2: dc in next st (mark this st as S), 3 dc in marked st S."
    assert last(RING + "2dc.W,4dc,2dc@W").endswith("dc in each of the 2 marked sts W.")
    # a label that was never defined is still described, but not guessed at
    assert last(RING + "3dc@W") == "Round 2: 3 dc in marked st/space W."
    assert last(RING + "ss@[%,0]") == "Round 2: ss to first st."


def test_attachment_to_a_leg_with_second_head():
    out = describe("10ch\nsk,9sc,turn\nch,sc,ch,5ch.L,5sc@1L,8sc")
    assert out[-1] == (
        "Row 2: ch 1, sc in next st, ch 1, ch 5 (mark this space as L), "
        "5 sc in marked space L (second attachment head, worked back along it), sc in next 8 sts."
    )


def test_groups_worked_into_one_place():
    out = describe("ring.R0\n(3dc,2ch.A,3dc,2ch.B)@R0\n(2dc,tr.E,2dc)@A\n(6sc)@B")
    assert out[1] == "Round 1: (3 dc, ch 2 (mark this space as A), 3 dc, ch 2 (mark this space as B)) all in magic ring."
    assert out[2] == "Round 2: (2 dc, tr (mark this st as E), 2 dc) all in marked space A."
    assert out[3] == "Round 3: 6 sc in marked space B."
    # unknown label: say so rather than guess st or space
    assert last(RING + "(2dc,tr.E,2dc)@A") == "Round 2: (2 dc, tr (mark this st as E), 2 dc) all in marked st/space A."
    # labelled stitches inside a group worked into the ring
    out = describe("ring.R0\n(dc.S,2dc,2ch.A,3dc,2ch.B,3dc)@R0,ss@S")
    assert out[1] == (
        "Round 1: (dc (mark this st as S), 2 dc, ch 2 (mark this space as A), 3 dc, "
        "ch 2 (mark this space as B), 3 dc) all in magic ring, ss to marked st S."
    )


def test_group_label():
    assert last(RING + "(3ch,sc).B") == "Round 2: (ch 3, sc in next st) (mark all of these as B)."


def test_square_rounds_end_to_end():
    code = (
        "ring.R0\n"
        "(3dc.S,2ch.A,3dc,2ch.B,3dc,2ch.C,3dc,2ch.D)@R0\n"
        "(2dc.W,2ch.E,2dc)@A,3dc,(2dc,2ch.F,2dc)@B,3dc,(2dc,2ch.G,2dc)@C,3dc,(2dc,2ch.H,2dc)@D,3dc@S,ss\n"
        "(2dc,2ch,2dc)@E,7dc,(2dc,2ch,2dc)@F,7dc,(2dc,2ch,2dc)@G,7dc,(2dc,2ch,2dc)@H,5dc,2dc@W"
    )
    out = describe(code)
    assert len(out) == 4 and not any("UNSUPPORTED" in l for l in out)
    assert out[2].startswith(
        "Round 2: (2 dc (mark these 2 sts as W), ch 2 (mark this space as E), 2 dc) all in marked space A, dc in next 3 sts"
    )
    assert "dc in each of the 3 marked sts S" in out[2]
    assert out[3].startswith("Round 3: (2 dc, ch 2, 2 dc) all in marked space E, dc in next 7 sts")
    assert out[3].endswith("dc in next 5 sts, dc in each of the 2 marked sts W.")


def test_same_stitch_attachment():
    assert last(RING + "dc,ch,dc@[@]") == "Round 2: dc in next st, ch 1, dc in the same st."
    assert last(RING + "dc2inc,ch,dc2inc@[@]") == "Round 2: 2 dc in next st, ch 1, 2 dc in the same st."
    assert last(RING + "22*[dc,ch,dc@[@],ch,dc@[@]]") == (
        "Round 2: (dc in next st, ch 1, dc in the same st, ch 1, dc in the same st) 22 times."
    )


def test_skips():
    assert last(RING + "sk,5sc") == "Round 2: skip next st, sc in next 5 sts."
    assert last(RING + "2sk,4sc") == "Round 2: skip 2, sc in next 4 sts."
    assert last(RING + "4sk") == "Round 2: skip 4."


def test_foundation_rows_with_skips():
    assert describe("17ch\n2sk,15dc,turn\n15dc") == [
        "Ch 17.",
        "Row 1: dc in 4th ch from hook and in each ch across, turn.",
        "Row 2: dc in next 15 sts.",
    ]
    assert describe("11ch\nsk,10sc,turn")[1] == "Row 1: sc in 2nd ch from hook and in each ch across, turn."
    assert describe("11ch\nsk,10sc,ch,turn\nch,10sc")[1] == (
        "Row 1: sc in 2nd ch from hook and in each ch across, ch 1, turn."
    )
    assert describe("15ch\nsk,14hdc,turn")[1] == "Row 1: hdc in 3rd ch from hook and in each ch across, turn."
    # skipped chains that do not count as a stitch are said literally, in chains
    assert describe("11ch\n3sk,8dc,turn")[1] == "Row 1: skip next 3 ch, dc in next 8 ch, turn."
    assert describe("11ch\nsk,3*[dc,ch,sk],turn")[1] == (
        "Row 1: skip next ch, (dc in next ch, ch 1, skip next ch) 3 times, turn."
    )


def test_turning_chains_and_turn():
    assert describe("11ch\nsk,10sc,turn\nch,turn")[-1] == "Row 2: ch 1, turn."
    assert describe("11ch\nsk,10sc,turn\n3ch,10dc,turn")[-1] == "Row 2: ch 3, dc in next 10 sts, turn."
    assert describe("11ch\nsk,10sc,turn\nch,10sc,turn\n10sc")[-2] == "Row 2: ch 1, sc in next 10 sts, turn."
    assert last(RING + "turn") == "Turn."


@pytest.mark.parametrize(
    "code,english",
    [
        ("dc5inc", "5 dc in next st"),
        ("sc7inc", "7 sc in next st"),
        ("tr2inc", "2 tr in next st"),
        ("3dc4inc", "4 dc in each of next 3 sts"),
        ("sc3tog", "sc3tog"),
        ("2dc4tog", "(dc4tog) 2 times"),
        ("scbl", "sc in back loop only of next st"),
        ("2hdcfl", "hdc in front loop only of next 2 sts"),
        ("trbl", "tr in back loop only of next st"),
        ("dtrfl", "dtr in front loop only of next st"),
        ("scbl2tog", "sc2tog in back loops only"),
        ("hdcfl2tog", "hdc2tog in front loops only"),
        ("dcbl2inc", "2 dc in back loop only of next st"),
        ("fpdc", "front post dc around next st"),
        ("2bptr", "back post tr around next 2 sts"),
        ("bpsc2tog", "back post sc2tog"),
        ("fpsc", "front post sc around next st"),
        ("dc3bobble", "3-dc bobble in next st"),
        ("tr4bobble", "4-tr bobble in next st"),
        ("dc4pc", "4-dc popcorn in next st"),
        ("hdc3puff", "3-hdc puff in next st"),
        ("2dc3bobble", "3-dc bobble in each of next 2 sts"),
        ("rsc", "reverse sc in next st"),
        ("rscbl", "reverse sc in back loop only of next st"),
        ("ssfl", "ss in front loop only of next st"),
        ("picot3", "3-ch picot (ch 3, ss back into the st before it)"),
        ("dtr", "dtr in next st"),
        ("trtr", "trtr in next st"),
        ("trtrbl", "trtr in back loop only of next st"),
    ],
)
def test_stitch_names(code, english):
    assert last(RING + code) == f"Round 2: {english}."


def test_stitch_names_inside_a_group_worked_into_one_place():
    assert last(RING + "(dc3bobble,2dcbl,picot3)@R0") == (
        "Round 2: (3-dc bobble, 2 dc (back loop only), 3-ch picot (ch 3, ss back into the st before it)) all in magic ring."
    )


def test_partial_repeat_marker():
    assert last(RING + "4*[2sc,>,sc2inc]") == (
        "Round 2: (sc in next 2 sts, [marker], 2 sc in next st) 4 times; on the last repeat stop at the marker."
    )
    assert last(RING + "[2sc,>,sc2inc]*4") == last(RING + "4*[2sc,>,sc2inc]")
    assert describe("12ch\nsk,11sc,turn\nch,4*[2sc,>,sc2inc],turn\nch,14sc")[2] == (
        "Row 2: ch 1, (sc in next 2 sts, [marker], 2 sc in next st) 4 times; "
        "on the last repeat stop at the marker, turn."
    )
    assert last(RING + "3*[2sc,<,sc2inc]").endswith("on the first repeat start at the marker.")
    # a marker outside a repeat means nothing: flag it
    assert last(RING + "2sc,>,sc") == "UNSUPPORTED: 2sc,>,sc"


def test_multi_line_answers_one_sentence_per_line():
    out = describe("ring.R0\n(6sc)@R0\n(2dc,tr.E,2dc)@A\n6sc")
    assert len(out) == 4 and out[0] == "Make a magic ring."


def test_unsupported_is_flagged_not_guessed():
    out = describe("ring.R0\n(6sc)@R0\n6sc,ss@[-1,3]\nCOLOR: red\n6sc.A.B@[2;1]")
    assert out[0] == "Make a magic ring."
    assert out[2] == "UNSUPPORTED: 6sc,ss@[-1,3]"
    assert out[3] == "UNSUPPORTED: COLOR:red"
    assert out[4].startswith("UNSUPPORTED: ")


def test_blank_lines_and_comments_are_skipped():
    assert describe("# a comment\nring.R0\n\n(6sc)@R0\n") == ["Make a magic ring.", "Round 1: 6 sc in magic ring."]


def test_one_sentence_per_code_line():
    code = "ring.R0\n(6sc)@R0\n6*[sc2inc]\n6*[sc,sc2inc]"
    assert len(describe(code)) == len(code.splitlines())


# ---------------------------------------------------------------- round trip
def roundtrip(text):
    """English -> code1 -> English2 -> code2. Returns (code1, english2, code2)."""
    first = E.translate(text)
    assert first.all_parsed, [l.reason for l in first.lines if not l.parsed]
    code1 = first.code
    english2 = "\n".join(describe(code1))
    assert "UNSUPPORTED" not in english2, english2
    second = E.translate(english2)
    assert second.all_parsed, (english2, [l.reason for l in second.lines if not l.parsed])
    return code1, english2, second.code


def counts(code):
    result = E.check(code)
    assert result.ok, result.error
    return [(r.index, r.stitch_count, r.stitch_types) for r in result.rows]


def circle(rounds, stitch="sc", decrease_from=None):
    """A flat circle: 6 in the ring, then +6 per round. Optionally decrease back down."""
    lines = [f"Round 1: 6 {stitch} in magic ring"]
    for r in range(2, rounds + 1):
        k = r - 2
        group = "2 {s} in next st" if k == 0 else f"{{s}} in next {k} sts, 2 {{s}} in next st" if k > 1 else "{s} in next st, 2 {s} in next st"
        lines.append(f"Round {r}: ({group.format(s=stitch)}) 6 times")
    if decrease_from:
        for m in range(rounds, rounds - decrease_from, -1):
            k = m - 2
            if k == 0:
                group = f"{stitch}2tog"
            elif k == 1:
                group = f"{stitch} in next st, {stitch}2tog"
            else:
                group = f"{stitch} in next {k} sts, {stitch}2tog"
            lines.append(f"Round {len(lines) + 1}: ({group}) 6 times")
    return "\n".join(lines)


GENERATED = (
    [circle(n) for n in range(3, 9)]
    + [circle(n, stitch="dc") for n in (3, 5, 8)]
    + [circle(n, stitch="hdc") for n in (4, 7)]
    + [circle(n, decrease_from=d) for n, d in ((4, 1), (5, 2), (6, 3), (8, 4))]
    + [
        "Round 1: 6 sc in magic ring\nRound 2: (2 sc in next st) 6 times\nRound 3: sc in next 12 sts, ss to first st",
        "Round 1: 8 dc in magic ring\nRound 2: (dc in next st, dc2tog) 2 times, dc in next 2 sts",
        "Ch 11\nRow 1: sc in 2nd ch from hook and in each ch across, turn.\nRow 2: ch 1, sc in next 10 sts, turn",
        "Ch 11\nRow 1: sc in 2nd ch from hook and in each ch across, turn.\n"
        "Row 2: ch 3, dc in next 10 sts, turn\nRow 3: ch 2, hdc in next 10 sts, turn",
        "Ch 11\nRow 1: sc in 2nd ch from hook and in each ch across, turn.\n"
        "Row 2: ch 1, sc in next 8 sts, sc2tog, turn\nRow 3: ch 1, sc in next 9 sts",
    ]
)


@pytest.mark.parametrize("text", GENERATED, ids=lambda t: t.splitlines()[0] + f" ({len(t.splitlines())} lines)")
def test_round_trip_is_exact(text):
    code1, english2, code2 = roundtrip(text)
    assert code1 == code2, f"{english2!r}"
    # and the code still checks out with the same counts
    assert counts(code1) == counts(code2)
