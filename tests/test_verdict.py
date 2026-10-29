"""decide_verdict(): stated-vs-computed counts, counting readings, and the five verdict kinds.

Most tests hand the verdict engine-neutral check results (RowInfo lists), so they do not
depend on any engine syntax; a few run real encoded patterns through the engine.
"""

from frogless.engine import CheckError, CheckResult, RowInfo, StitchInfo, get_engine
from frogless.pipeline.report import RowResult
from frogless.pipeline.verdict import PLAIN, TURN_COUNTS, decide_verdict
from frogless.testset.generators import base_cases, load_config
from frogless.testset.inject import injected_cases
from frogless.testset.spec import Item, Repeat, Spec
from scripts.run_testset import verdict_rows

ENGINE = get_engine()


def info(index, count, **types):
    return RowInfo(index, count, types or {"sc": count})


def graph_row(index, kinds):
    """A row with its stitch graph: `kinds` are the row's stitches in working order ("ch" first = turning chain)."""
    types = {}
    for k in kinds:
        types[k] = types.get(k, 0) + 1
    return RowInfo(index, len(kinds), types, stitches=[StitchInfo(i, k) for i, k in enumerate(kinds)])


def run(lines, infos, error=None, **row_fields):
    """lines: [(source, has_code)]; infos: the engine rows of the lines that have code, in order."""
    rows = [RowResult(index=i, source=src, code="x" if coded else "", **row_fields)
            for i, (src, coded) in enumerate(lines)]
    result = CheckResult(ok=error is None, error=error, rows=infos)
    return decide_verdict(ENGINE, "", rows, result)


def count_error(row, message="Row has the wrong number of stitches."):
    return CheckError(message, row=row, kind="count")


# ---- extra stitch is caught at its own row ----
CIRCLE = [("Round 1: 6 sc in ring (6)", True), ("Round 2: inc in each st around (12)", True),
          ("Round 3: sc around (12)", True)]


def test_matching_counts_work():
    v, stated, computed = run(CIRCLE, [info(1, 6), info(2, 12), info(3, 12)])
    assert v.kind == "works" and v.row is None
    assert stated == computed == {1: 6, 2: 12, 3: 12}


def test_extra_stitch_caught_at_its_own_row_not_the_next():
    # round 2 makes 13 but says 12; the engine only complains one row later
    v, stated, computed = run(CIRCLE, [info(1, 6), info(2, 13), info(3, 12)], error=count_error(3))
    assert (v.kind, v.row) == ("breaks", 2)
    assert v.message.startswith("Row 2: pattern says 12, the instructions make 13")
    assert stated[2] == 12 and computed[2] == 13


def test_extra_stitch_in_the_last_row_is_caught():
    v, _, _ = run(CIRCLE, [info(1, 6), info(2, 12), info(3, 13)])  # the engine says ok
    assert (v.kind, v.row) == ("breaks", 3)
    assert "pattern says 12, the instructions make 13" in v.message


def test_engine_error_without_a_stated_count_still_breaks():
    lines = [("Round 1: 6 sc in ring (6)", True), ("Round 2: sc around", True)]
    v, _, _ = run(lines, [info(1, 6), info(2, 5)], error=count_error(2, "Row 2 leaves 1 stitch unworked."))
    assert (v.kind, v.row) == ("breaks", 2)
    assert "leaves 1 stitch" in v.message


def test_earliest_problem_wins_when_engine_error_comes_first():
    lines = CIRCLE
    v, _, _ = run(lines, [info(1, 6), info(2, 14), info(3, 13)], error=count_error(2, "Row 2 has too many."))
    assert (v.kind, v.row) == ("breaks", 2)


def test_range_line_applies_its_count_to_each_row():
    src = "Rows 2-4: sc across (12)"
    lines = [("Row 1: sc (12)", True)] + [(src, True)] * 3
    ok, _, _ = run(lines, [info(1, 12)] * 4)
    assert ok.kind == "works"
    v, stated, _ = run(lines, [info(1, 12), info(2, 12), info(3, 12), info(4, 13)])
    assert (v.kind, v.row) == ("breaks", 4) and stated == {1: 12, 2: 12, 3: 12, 4: 12}


def test_multi_size_count_is_not_checked():
    v, stated, _ = run([("Round 1: sc in ring (6 [8, 10])", True)], [info(1, 6)])
    assert v.kind == "works" and stated == {}


# ---- bare counts and chains ----
MESH = ["ch"] + ["sc", "ch"] * 4 + ["sc"]  # a turning chain, then 5 sc with a ch-1 space between each: 5 sc, 4 chains


def mesh_rows(second, third=None):
    lines = [("Ch 11.", True), ("Row 1: sc across (10)", True), (f"Row 2: ch 1, sc, [ch 1, sk 1, sc] x4 ({second})", True)]
    infos = [info(0, 11, ch=11), info(1, 10), graph_row(2, MESH)]
    return lines, infos


def test_bare_count_counts_mesh_chains_but_not_the_turning_chain():
    v, stated, computed = run(*mesh_rows(9))  # 5 sc + 4 mesh chains; the turning chain is left out
    assert v.kind == "works" and not v.chains_left_out
    assert stated == {1: 10, 2: 9} and computed == {1: 10, 2: 9}  # row 0 is the foundation chain
    v, _, _ = run(*mesh_rows(10))  # ... which would be 10 with the turning chain counted
    assert (v.kind, v.row) == ("breaks", 2)
    assert "pattern says 10, the instructions make 9" in v.message


def test_corner_chains_in_a_round_count_but_the_starting_chain_does_not():
    lines = [("Round 1: 4 sc in ring (4)", True), ("Round 2: ch 1, (sc, ch 2, sc) in each st around (12)", True)]
    kinds = ["ch"] + ["sc", "ch", "ch", "sc"] * 2  # starting ch 1, then two corners of sc, ch 2, sc
    v, _, computed = run(lines, [info(1, 4), graph_row(2, kinds)])
    assert v.kind == "breaks" and "the instructions make 8" in v.message  # 4 sc + 4 corner chains = 8
    lines[1] = (lines[1][0].replace("(12)", "(8)"), True)
    v, _, computed = run(lines, [info(1, 4), graph_row(2, kinds)])
    assert v.kind == "works" and computed[2] == 8


def test_a_slip_stitch_join_before_the_starting_chain_is_passed_over():
    lines = [("Round 1: 4 sc in ring (4)", True), ("Round 2: sl st in first sc, ch 2, sc around (4)", True)]
    v, _, _ = run(lines, [info(1, 4), graph_row(2, ["ss", "ch", "ch", "sc", "sc", "sc", "sc"])])
    assert v.kind == "works"


def test_bare_count_may_leave_chains_out():
    lines = [("Ch 11.", True), ("Row 1: sc across (10)", True), ("Row 2: sc across (10)", True)]
    v, _, computed = run(lines, [info(0, 11, ch=11), info(1, 10), info(2, 11, ch=1, sc=10)])
    assert v.kind == "works" and computed[2] == 10 and not v.chains_left_out


def test_typed_count_counts_that_stitch_only():
    lines = [("Ch 11.", True), ("Row 1: sc across (10)", True), ("Row 2: sc across (10 sc)", True),
             ("Row 3: sc across (11 sc)", True)]
    infos = [info(0, 11, ch=11), info(1, 10), info(2, 11, ch=1, sc=10), info(3, 11, ch=1, sc=10)]
    v, _, _ = run(lines, infos)
    assert (v.kind, v.row) == ("breaks", 3)  # 11 sc is wrong even though 11 counts the chain


# ---- the turning chain: not counted, unless the pattern says so or the counts fit only that way ----
def dc_rows(first, *stated, say=""):
    """Ch 16 and dc rows of 13 dc after a 3-chain; every row states its own count. Row 1 ("dc in
    4th ch from hook") makes 13 dc from the 13 chains it can use, 14 if the skipped chains count."""
    lines = [("Ch 16.", True), (f"Row 1: dc in 4th ch from hook and across ({first})", True)]
    infos = [info(0, 16, ch=16), info(1, 13, dc=13)]
    for n, count in enumerate(stated, 2):
        lines.append((f"Row {n}: ch 3{say}, dc across ({count})", True))
        infos.append(info(n, 16, ch=3, dc=13))
    return lines, infos


def test_turning_chain_is_not_counted_by_default():
    v, _, computed = run(*dc_rows(13, 13, 13, 13))
    assert (v.kind, v.reading) == ("works", "") and computed[3] == 13


def test_turning_chain_counted_as_a_fallback_when_the_counts_fit_only_that_way():
    v, _, computed = run(*dc_rows(14, 14, 14, 14))
    assert v.kind == "works" and v.reading == TURN_COUNTS
    assert computed[1] == 14 and computed[2] == 14 and "turning chain counts as a stitch" in v.message


def test_the_pattern_saying_counts_as_settles_it_with_no_fallback_note():
    v, _, computed = run(*dc_rows(14, 14, 14, say=" (counts as first dc)"))
    assert (v.kind, v.reading) == ("works", "") and computed[2] == 14
    v, _, _ = run(*dc_rows(14, 13, 13, say=" (does not count as a st)"))
    assert (v.kind, v.row) == ("breaks", 1)  # the pattern says no, so row 1's 14 is wrong


def test_code_that_already_writes_the_counted_chain_as_a_stitch_needs_no_fallback():
    lines = [("Ch 17.", True), ("Row 1: dc in 4th ch from hook and across (15)", True),
             ("Row 2: ch 3 (counts as dc), dc across (15)", True)]
    v, _, computed = run(lines, [info(0, 17, ch=17), info(1, 15, dc=15), info(2, 15, dc=15)])
    assert (v.kind, v.reading) == ("works", "") and computed == {1: 15, 2: 15}


def test_counts_as_in_a_round_with_corner_chains_does_not_invent_a_stitch():
    # the starting ch 3 is written as a dc already; the corner chains are not a turning chain
    lines = [("Round 1: in a ring, ch 3 (counts as dc), 2 dc, ch 2, 3 dc (12 dc)", True),
             ("Round 2: ch 3 (counts as dc), dc in each st, 2 dc in each ch-2 space (20 dc)", True)]
    v, _, computed = run(lines, [info(1, 14, dc=12, ch=2), info(2, 26, dc=20, ch=6)])
    assert (v.kind, v.reading) == ("works", "") and computed == {1: 12, 2: 20}


def test_counts_as_on_a_row_coded_with_its_chain_adds_the_stitch():
    lines = [("Ch 16.", True), ("Row 1: dc in 4th ch from hook and across (14)", True),
             ("Row 2: ch 3 (counts as first dc), dc across (14)", True)]
    v, _, computed = run(lines, [info(0, 16, ch=16), info(1, 13, dc=13), info(2, 16, ch=3, dc=13)])
    assert (v.kind, v.reading) == ("works", "") and computed == {1: 14, 2: 14}  # the pattern said so: no warning


def test_minority_rows_break_under_the_majority_reading():
    lines, infos = dc_rows(14, 14, 14, 13, 14)  # row 4 follows the other habit
    v, _, _ = run(lines, infos)
    assert (v.kind, v.row, v.reading) == ("breaks", 4, TURN_COUNTS)
    assert "pattern says 13, the instructions make 14" in v.message
    v, _, _ = run(*dc_rows(13, 13, 13, 14, 13))  # and the other way round: the default
    assert (v.kind, v.row, v.reading) == ("breaks", 4, "")


def test_equally_good_readings_that_disagree_are_ambiguous():
    v, _, _ = run(*dc_rows(13, 14))  # row 1 follows one habit, row 2 the other
    assert v.kind == "ambiguous"
    assert v.row == 1 and len(v.readings) == 2
    assert any(PLAIN in r for r in v.readings) and any(TURN_COUNTS in r for r in v.readings)


def test_a_single_turned_row_follows_the_reading_that_fits():
    v, _, _ = run(*dc_rows(14))
    assert (v.kind, v.reading) == ("works", TURN_COUNTS)
    v, _, _ = run(*dc_rows(14, 14))
    assert (v.kind, v.reading) == ("works", TURN_COUNTS)


# ---- bare counts leave chain spaces out; counting them is a flagged fallback ----
def test_bare_count_that_fits_only_with_all_chains_left_out_passes_with_a_note():
    v, _, computed = run(*mesh_rows(5))  # the 5 sc only
    assert v.kind == "works" and v.chains_left_out
    assert computed[2] == 5
    v, _, _ = run(*mesh_rows(9))  # the default: mesh chains counted
    assert v.kind == "works" and not v.chains_left_out


def test_typed_count_is_unchanged_by_chains():
    lines, infos = mesh_rows(5)
    lines[2] = (lines[2][0].replace("(5)", "(5 sc)"), True)
    v, _, _ = run(lines, infos)
    assert v.kind == "works" and not v.chains_left_out
    lines[2] = (lines[2][0].replace("(5 sc)", "(9 sc)"), True)
    v, _, _ = run(lines, infos)
    assert (v.kind, v.row) == ("breaks", 2)


# ---- unreadable versus breaks before the unreadable row ----
def test_unreadable_when_a_row_has_no_code():
    lines = CIRCLE[:2] + [("Round 3: *sc, inc; rep from * around (18)", False)]
    v, stated, _ = run(lines, [info(1, 6), info(2, 12)])
    assert v.kind == "unreadable" and "Round 3" in v.message
    assert stated == {1: 6, 2: 12, 3: 18}


def test_break_before_the_first_unreadable_row_is_reported():
    lines = [CIRCLE[0], ("Round 2: inc in each st around (12)", True),
             ("Round 3: something odd (18)", False), ("Round 4: sc around (18)", True)]
    v, _, _ = run(lines, [info(1, 6), info(2, 13), info(3, 18)])
    assert (v.kind, v.row) == ("breaks", 2)


def test_break_after_the_unreadable_row_is_not_reported():
    lines = [CIRCLE[0], ("Round 2: something odd (12)", False), ("Round 3: sc around (12)", True)]
    v, stated, computed = run(lines, [info(1, 6), info(2, 13)])
    assert v.kind == "unreadable"
    assert computed == {1: 6, 3: 13}  # the unread row keeps its number; later rows are numbered by position


def test_nothing_to_check():
    v, stated, computed = decide_verdict(ENGINE, "", [RowResult(0, "Round 1: ???")], None)
    assert v.kind == "unreadable" and stated == computed == {}


# ---- model rows ----
def test_model_rows_not_confirmed_give_works_unverified():
    lines = CIRCLE
    infos = [info(1, 6), info(2, 12), info(3, 12)]
    rows = [RowResult(i, s, code="x", origin="model" if i in (1, 2) else "rules",
                      faithful=False if i == 1 else None) for i, (s, _) in enumerate(lines)]
    v, _, _ = decide_verdict(ENGINE, "", rows, CheckResult(ok=True, rows=infos))
    assert v.kind == "works_unverified" and v.rows == [2, 3]
    assert "rows 2, 3" in v.message
    for r in rows:
        r.faithful = True
    v, _, _ = decide_verdict(ENGINE, "", rows, CheckResult(ok=True, rows=infos))
    assert v.kind == "works"


def test_a_break_beats_works_unverified():
    rows = [RowResult(i, s, code="x", origin="model") for i, (s, _) in enumerate(CIRCLE)]
    v, _, _ = decide_verdict(ENGINE, "", rows, CheckResult(ok=True, rows=[info(1, 6), info(2, 12), info(3, 14)]))
    assert (v.kind, v.row) == ("breaks", 3)


# ---- with the real engine ----
def rows_of(spec, english):
    return verdict_rows(ENGINE, {"spec": spec, "english": english})


def verdict_of(spec, english):
    rows = rows_of(spec, english)
    code = "\n".join(r.code for r in rows)
    return decide_verdict(ENGINE, english, rows, ENGINE.check(code))


def broken_circle(last_stated):
    """Round 3 works into 12 stitches but makes 19 (an inc where a sc belongs)."""
    spec = Spec("ring", "rounds", [
        [Item("st", "sc", 6)], [Item("inc", "sc", 6)],
        [Repeat([Item("st", "sc"), Item("inc", "sc")], 5), Item("inc", "sc", 2)],
        [Item("st", "sc", 18)]], stitch="sc")
    english = ("R1: 6 sc in magic ring (6)\nR2: inc in each st around (12)\n"
               f"R3: *sc, inc* x 5, inc in next 2 sts ({last_stated})\nR4: sc around (18)")
    return spec, english


def test_real_engine_catches_the_late_extra_stitch_at_its_row():
    spec, english = broken_circle(18)
    rows = rows_of(spec, english)
    result = ENGINE.check("\n".join(r.code for r in rows))
    assert not result.ok and result.error.row == 4  # the engine alone blames the next row
    v, stated, computed = decide_verdict(ENGINE, english, rows, result)
    assert (v.kind, v.row) == ("breaks", 3)
    assert stated[3] == 18 and computed[3] == 19


def test_real_engine_honest_count_moves_the_break_to_the_next_row():
    spec, english = broken_circle(19)
    v, _, _ = verdict_of(spec, english)
    assert (v.kind, v.row) == ("breaks", 4)  # R4 is the one that no longer fits


def test_real_engine_unparsable_code_breaks_at_that_row():
    spec, english = broken_circle(18)
    rows = rows_of(spec, english)
    rows[3].code = "???"  # round 2
    v, _, _ = decide_verdict(ENGINE, english, rows, ENGINE.check("\n".join(r.code for r in rows)))
    assert (v.kind, v.row) == ("breaks", 3)


def test_bench_known_gap_cases_are_judged_right():
    cfg = load_config()
    bases = base_cases(cfg)
    gaps = [c for c in injected_cases(cfg, bases) if c["known_gap"]]
    assert len(gaps) >= 10
    for case in gaps:
        rows = rows_of(case["spec"], case["english"])
        v, _, _ = decide_verdict(ENGINE, case["english"], rows, ENGINE.check("\n".join(r.code for r in rows)))
        assert (v.kind, v.row) == ("breaks", case["expected"]["break_row"]), case["id"]


# ---- wording clues about the turning chain settle a tie, never a statement or the counts ----
def test_next_st_or_first_st_settles_a_tie_between_the_two_readings():
    lines, infos = dc_rows(13, 14)  # row 1 follows one habit, row 2 the other: ambiguous (see above)
    lines[2] = ("Row 2: ch 3, dc in next st and across (14)", True)  # starts in the NEXT stitch: the chain counts
    v, _, _ = run(lines, infos)
    assert (v.kind, v.row, v.reading) == ("breaks", 1, TURN_COUNTS)
    lines[2] = ("Row 2: ch 3, dc in first st and across (14)", True)  # starts in the FIRST stitch: it does not
    v, _, _ = run(lines, infos)
    assert (v.kind, v.row, v.reading) == ("breaks", 2, "")


def test_a_clue_does_not_override_counts_that_fit_the_default():
    lines, infos = dc_rows(13, 13, 13)
    lines[3] = ("Row 3: ch 3, dc in next st and across (13)", True)
    v, _, computed = run(lines, infos)
    assert (v.kind, v.reading) == ("works", "") and computed[3] == 13


def test_a_last_stitch_in_the_turning_chain_hints_that_it_counts_but_a_statement_wins():
    lines, infos = dc_rows(13, 14)
    lines[2] = ("Row 2: ch 3, dc across, dc in top of turning ch (14)", True)
    v, _, _ = run(lines, infos)
    assert (v.kind, v.row, v.reading) == ("breaks", 1, TURN_COUNTS)
    lines, infos = dc_rows(13, 13, 13)
    lines[2] = ("Row 2: ch 3, dc across, dc in 2nd ch of turning ch (13)", True)
    lines[3] = ("Row 3: ch 3 (does not count as a stitch), dc across (13)", True)
    v, _, computed = run(lines, infos)
    assert (v.kind, v.reading) == ("works", "") and computed[2] == 13  # stays "not counted"
