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
    assert out[-1] == "Round 2: sc in next 6 sts, ch 2, ss in next st."
    assert describe("ring.R0\n(6sc)@R0\n6sc,ch")[-1] == "Round 2: sc in next 6 sts, ch 1."


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


def test_labels_and_attachments():
    assert describe("ring.R0\n(6sc)@R0\n3sc,sc.A,2sc") [-1] == "Round 2: sc in next 3 sts, sc in next st (mark as A), sc in next 2 sts."
    assert describe("ring.R0\n(6sc)@R0\n6sc,ss@A")[-1] == "Round 2: sc in next 6 sts, ss in marked st A."


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
