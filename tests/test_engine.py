"""Engine tests. These run the real engine through Node, so Node must be installed."""

from frogless.engine import get_engine

CIRCLE = "ring.R0\n(6sc)@R0\n6*[sc2inc]\n6*[sc,sc2inc]"


def test_valid_circle_passes_with_correct_counts():
    result = get_engine().check(CIRCLE)
    assert result.ok, result.error
    assert result.error is None
    assert [(r.index, r.stitch_count) for r in result.rows] == [(1, 6), (2, 12), (3, 18)]
    assert all(r.unworked == 0 and r.overflow == 0 for r in result.rows)
    assert result.stats["total_stitches"] == 36


def test_too_many_stitches_names_the_row():
    code = CIRCLE.replace("6*[sc,sc2inc]", "13sc")  # round 3 has 13 sts into 12
    result = get_engine().check(code)
    assert not result.ok
    assert result.error.kind == "count"
    assert result.error.row == 3
    assert result.rows[2].overflow == 1


def test_too_few_stitches_names_the_row():
    code = CIRCLE.replace("6*[sc,sc2inc]", "11sc")  # one stitch left unworked
    result = get_engine().check(code)
    assert not result.ok
    assert result.error.row == 3
    assert result.rows[2].unworked == 1


def test_unknown_stitch_is_an_error_with_row():
    result = get_engine().check("ring.R0\n(6sc)@R0\nfoo\nsc")
    assert not result.ok
    assert result.error.kind == "invalid"
    assert result.error.row == 2
    assert "foo" in result.error.message


def test_translate_returns_code_and_a_flag():
    text = (
        "Round 1: 6 sc in ring\n"
        "Round 2: 2 sc in each st around\n"
        "Round 3: *sc, 2 sc in next st* 6 times"
    )
    result = get_engine().translate(text)
    parsed = [line for line in result.lines if line.parsed]
    flagged = [line for line in result.lines if not line.parsed]
    assert any(line.code == "6*[sc2inc]" for line in parsed)
    assert len(flagged) == 1
    assert "3" in flagged[0].source and flagged[0].reason
    assert not result.all_parsed
    # the parsed part (ring + rounds 1-2) is valid engine code
    assert get_engine().check(result.code).ok


def test_rows_turn_even_when_the_range_does_not_say_so():
    text = "Ch 13.\nRow 1: sc in 2nd ch from hook and across, turn (12)\nRows 2-4: ch 1, sc across (12)"
    rows = [line for line in get_engine().translate(text).lines if line.source.startswith("row")]
    assert all(line.code.endswith("turn") for line in rows[:-1])
    assert not rows[-1].code.endswith("turn")  # the last row of the piece isn't turned


def test_rounds_are_not_turned():
    lines = get_engine().translate("Round 1: 6 sc in ring\nRound 2: inc in each st around (12)").lines
    assert not any("turn" in line.code for line in lines)


def test_stitches_lists_basics():
    names = get_engine().stitches()
    assert {"sc", "dc", "ch"} <= set(names)


def test_r_labels_on_a_flat_piece_become_rows():
    import sys

    _label_rows = sys.modules[type(get_engine()).__module__]._label_rows  # the adapter's own helper

    flat = "Ch 21.\nR1: sc in 2nd ch from hook, turn (20)\nR2-5 (RS): ch 1, sc across (20)"
    assert _label_rows(flat) == "Ch 21.\nRow 1: sc in 2nd ch from hook, turn (20)\nRow 2-5 (RS): ch 1, sc across (20)"
    turned = "R1: sc in 2nd ch from hook\nR2: ch 1, sc across, turn"
    assert _label_rows(turned).startswith("Row 1:")
    rounds = "R1: 6 sc in a magic ring\nR2: 2 sc in each st around"
    assert _label_rows(rounds) == rounds  # a ring: rounds stay rounds
    assert _label_rows("R1: sc around (6)\nR2: inc around (12)") == "R1: sc around (6)\nR2: inc around (12)"


def test_flat_r_rows_are_translated_as_rows_and_turned():
    lines = get_engine().translate("Ch 21.\nR1: sc in 2nd ch from hook, turn (20)\nR2-3: ch 1, sc in each st across (20)").lines
    assert [l.source.split(":")[0] for l in lines[1:]] == ["row 1", "row 2-3", "row 2-3"]
    assert lines[2].code.endswith(",turn") and not lines[3].code.endswith("turn")


def test_turning_chain_written_before_turn_belongs_to_the_next_row():
    engine = get_engine()
    written = "17ch\n3sk,14dc,3ch,turn\n14dc,3ch,turn\n14dc"  # "..., ch 3, turn" at the end of each row
    result = engine.check(written)
    assert result.ok, result.error
    assert [r.stitch_types.get("ch", 0) for r in result.rows] == [17, 0, 3, 3]
    assert [r.stitch_count - r.stitch_types.get("ch", 0) for r in result.rows[1:]] == [14, 14, 14]
    # a row that already starts with its chain keeps it
    assert engine.check("11ch\nsk,10sc,ch,turn\nch,10sc").ok


def test_directive_only_code_is_recognised():
    engine = get_engine()
    for code in ["COLOR:white", "COLOR: red", "start_anew", "start_at@[2]", "COLOR:red\nstart_anew"]:
        assert engine.is_directive(code), code
    for code in ["12sc", "", "start_anew,6sc", "COLOR:red\n12sc"]:
        assert not engine.is_directive(code), code
