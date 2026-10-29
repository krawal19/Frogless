"""A chain written twice across a repeat boundary is read once; nothing else is dropped."""

from frogless.engine import CheckResult, RowInfo, get_engine
from frogless.patterns.repeats import merge_repeat_chains
from frogless.pipeline.check import _with_repeat_notes
from frogless.pipeline.messages import user_message
from frogless.pipeline.report import PatternReport, RowResult
from frogless.pipeline.verdict import decide_verdict

ROUND = "Round 1: Ch5(dc,ch2), [3dc into ring,ch2]x3, Ch 2, 2dc into ring, slst.[12dc]"


def test_the_chain_after_a_repeat_that_ends_with_it_is_read_once():
    text, notes = merge_repeat_chains(ROUND)
    assert text == "Round 1: Ch5(dc,ch2), [3dc into ring,ch2]x3, 2dc into ring, slst.[12dc]"
    assert len(notes) == 1
    assert notes[0].reading == "the 'ch 2' after the repeat is the same chain as the repeat's last 'ch 2' (written twice)"


def test_other_spellings_of_a_repeat():
    for before, after in [
        ("[dc, ch 2] x3, ch 2, dc", "[dc, ch 2] x3, dc"),
        ("(dc, ch 2) 3 times, ch 2, dc", "(dc, ch 2) 3 times, dc"),
        ("*dc, ch 2; rep from * 3 times, ch 2, dc", "*dc, ch 2; rep from * 3 times, dc"),
    ]:
        assert merge_repeat_chains(before)[0] == after


def test_no_other_chain_is_dropped():
    for text in [
        "[dc, ch 2] x3, ch 3, dc",            # a different number
        "[dc, ch 2] x3, 2 dc, ch 2",          # not directly adjacent
        "[dc, ch 2] x3, ch 20",               # a longer chain
        "[dc, ch 2] x3, ch 2 sp",             # a space, not a chain
        "[dc, ch 1, dc] x3, ch 2, dc",        # the repeat does not end with a chain
        "dc, ch 2, ch 2, dc",                 # no repeat at all
        "Ch 5(dc, ch 2), ch 2, dc",           # a bracket without a repeat count
    ]:
        assert merge_repeat_chains(text) == (text, []), text


def test_each_line_is_merged_on_its_own():
    text = "Round 1: [dc, ch 2] x4, ch 2, dc\nRound 2: [dc, ch 2] x4, dc\nRound 3: [dc, ch 3] x4, ch 3"
    out, notes = merge_repeat_chains(text)
    assert out.split("\n") == ["Round 1: [dc, ch 2] x4, dc", "Round 2: [dc, ch 2] x4, dc", "Round 3: [dc, ch 3] x4"]
    assert [n.reading[:12] for n in notes] == ["the 'ch 2' a", "the 'ch 3' a"]


def test_the_note_shows_as_an_interpreted_reading():
    text, notes = merge_repeat_chains(ROUND)
    # the translator rewrites the label and "x3" as "3 times" before the row is a RowResult
    source = "rnd 1: Ch5(dc,ch2), [3dc into ring,ch2] 3 times, 2dc into ring, slst.[12dc]"
    rows = [RowResult(0, source, code="x", faithful=None), RowResult(1, "rnd 2: sc around", code="y")]
    rows = _with_repeat_notes(rows, notes)
    assert rows[0].reading == notes[0].reading and rows[0].note == f"read as {notes[0].reading}"
    assert rows[1].reading == ""
    result = CheckResult(ok=True, rows=[RowInfo(1, 12, {"dc": 12}), RowInfo(2, 12, {"dc": 12})])
    verdict, _, _ = decide_verdict(get_engine(), text, rows, result)
    assert [(i.row, i.reading) for i in verdict.interpreted] == [(1, notes[0].reading)]
    assert "same chain as the repeat's last 'ch 2'" in user_message(PatternReport(text=text, rows=rows, verdict=verdict))


def test_an_existing_reading_keeps_its_own_text():
    _, notes = merge_repeat_chains(ROUND)
    row = RowResult(0, "rnd 1: Ch5(dc,ch2), [3dc into ring,ch2] 3 times", code="x", faithful=True, reading="sc in each st")
    (row,) = _with_repeat_notes([row], notes)
    assert row.reading == f"sc in each st; {notes[0].reading}"
