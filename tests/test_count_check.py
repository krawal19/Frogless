"""The stitch-count check on rows that use explicit attachments (labels, @R0, @[...]).

These run the real engine through Node, like tests/test_engine.py.
"""

from frogless.engine import get_engine

MESH_BASE = "12ch\nsk,sc,ch.A,sk,sc,ch.B,sk,sc,ch.C,sk,sc,ch.D,sk,sc,ch.E,sk,sc,turn\n"
MESH_ALL = MESH_BASE + "ch,sc,sc@E,ch,sc@D,ch,sc@C,ch,sc@B,ch,sc@A,sc"
MESH_NO_C = MESH_BASE + "ch,sc,sc@E,ch,sc@D,ch,sc@B,ch,sc@A,sc"

# A round of four corners (2 dc, 2 ch space, 2 dc pairs), then a square round worked around it.
CORNERS = "ring.R0\n(2dc,2ch.A,2dc,2ch.B,2dc,2ch.C,2dc,2ch.D)@R0\n"


def square(side="2dc"):
    return CORNERS + (
        f"2dc,(2dc,2ch.E,2dc)@A,{side},(2dc,2ch.F,2dc)@B,2dc,"
        "(2dc,2ch.G,2dc)@C,2dc,(2dc,2ch.H,2dc)@D"
    )


def rows_of(code):
    result = get_engine().check(code)
    return result, {r.index: r for r in result.rows}


def test_mesh_with_all_spaces_is_ok():
    result, rows = rows_of(MESH_ALL)
    assert result.ok, result.error
    assert rows[2].unworked == 0 and rows[2].overflow == 0


def test_mesh_that_misses_a_space_reports_unworked_on_that_row():
    result, rows = rows_of(MESH_NO_C)
    assert not result.ok
    assert result.error.kind == "count"
    assert result.error.row == 2
    assert rows[2].unworked >= 1
    assert rows[2].overflow == 0
    assert rows[1].unworked == 0  # the row of spaces itself is fine


def test_a_side_with_more_stitches_than_it_has_overflows():
    result, rows = rows_of(square("5dc"))  # the side has 2 stitches
    assert not result.ok
    assert result.error.row == 2
    assert rows[2].overflow == 3
    assert rows[2].unworked == 0


def test_a_side_with_fewer_stitches_leaves_one_unworked():
    result, rows = rows_of(square("dc"))
    assert not result.ok
    assert rows[2].unworked == 1


def test_correct_labelled_round_is_ok():
    result, rows = rows_of(square())
    assert result.ok, result.error
    assert [rows[i].stitch_count for i in (1, 2)] == [16, 32]
    # and a third round, worked into the corner spaces of the second
    third = square() + (
        "\n4dc,(2dc,2ch.I,2dc)@E,6dc,(2dc,2ch.J,2dc)@F,6dc,(2dc,2ch.K,2dc)@G,"
        "6dc,(2dc,2ch.L,2dc)@H,2dc"
    )
    result, rows = rows_of(third)
    assert result.ok, result.error
    assert rows[3].stitch_count == 48
    assert not rows_of(third.replace("@E,6dc", "@E,7dc"))[0].ok


def test_ch_one_between_clusters_bridges_the_cluster():
    # granny style: ch 1 passes over the dc cluster between two corner spaces
    code = (
        "ring.R0\n(3dc,2ch.A,3dc,2ch.B,3dc,2ch.C,3dc,2ch.D)@R0\n"
        "(3dc,2ch.E,3dc)@A,ch.I,(3dc,2ch.F,3dc)@B,ch.J,(3dc,2ch.G,3dc)@C,ch.K,(3dc,2ch.H,3dc)@D,ch.L"
    )
    result, _ = rows_of(code)
    assert result.ok, result.error
    # without the chains' bridge there is no way to leave the clusters alone
    no_bridge = code.replace(",ch.I,", ",").replace(",ch.J,", ",").replace(",ch.K,", ",")
    assert not rows_of(no_bridge)[0].ok


def test_plain_rows_keep_their_old_rules():
    # turning chains and the foundation chain are not required to be worked into
    assert get_engine().check("11ch\nsk,10sc,turn\nch,10sc").ok
    result, rows = rows_of("ring.R0\n(6sc)@R0\n6*[sc2inc]\n11sc")
    assert rows[3].unworked == 1


def test_row_info_stitches_graph():
    result, rows = rows_of("ring.R0\n(6sc)@R0\n6*[sc2inc]\n6*[sc,sc2inc]")
    assert result.ok, result.error
    # every row lists its stitches in working order
    assert [len(rows[i].stitches) for i in (1, 2, 3)] == [6, 12, 18]
    assert [s.position for s in rows[2].stitches] == list(range(12))
    assert {s.kind for s in rows[1].stitches} == {"sc"}
    assert {s.kind for s in rows[2].stitches} == {"sc2inc"}
    # round 1 works into the ring, which is not a stitch: nothing to point at
    assert all(s.into == [] for s in rows[1].stitches)
    # an increase makes two stitches in the same place of the row below
    assert [s.into for s in rows[2].stitches][:4] == [[(1, 0)], [(1, 0)], [(1, 1)], [(1, 1)]]
    assert [s.into for s in rows[3].stitches][:3] == [[(2, 0)], [(2, 1)], [(2, 1)]]


def test_row_info_stitches_chains_and_labels():
    result, rows = rows_of(MESH_ALL)
    assert result.ok, result.error
    row1 = rows[1].stitches
    assert [s.kind for s in row1] == ["sc", "ch", "sc", "ch", "sc", "ch", "sc", "ch", "sc", "ch", "sc"]
    assert [s.label for s in row1 if s.kind == "ch"] == ["A", "B", "C", "D", "E"]
    assert all(s.into == [] for s in row1 if s.kind == "ch")  # nothing is worked into by a chain
    # row 1 skips foundation chains: its stitches go into 1, 3, 5, ... of row 0
    assert [s.into for s in row1 if s.kind == "sc"] == [[(0, p)] for p in (1, 3, 5, 7, 9, 11)][:6]
    # row 2 works back into the chain spaces by label
    spaces = {s.label: s.position for s in row1 if s.kind == "ch"}
    row2_into = [s.into for s in rows[2].stitches]
    assert [(1, spaces["E"])] in row2_into and [(1, spaces["A"])] in row2_into


def test_corner_halves_share_a_place():
    result, rows = rows_of(square())
    row2 = rows[2].stitches
    corner = [s for s in row2 if s.kind == "dc" and s.into and len(s.into) == 2]
    assert corner  # the stitches worked into a two-chain corner space
    assert {i for s in corner for i in s.into} <= {(1, p) for p in range(len(rows[1].stitches))}


# ---- chain spaces written in pieces, and sides that are not fully worked -----------------------

# A chain-ring square: round 1 ends with "ch 2, ch 2" before the last two dc (one ch-4 space).
RING = "(4ch,ss@[%,0]).R_1\n(dc.S,2ch.A,3dc,2ch.B,3dc,2ch.C,3dc,2ch.D,2ch,2dc)@R_1,ss@S\n"
RING_ROUND_2 = (
    "(dc.W,2ch.E,2dc)@A,3dc,(2dc,2ch.F,2dc)@B,3dc,(2dc,2ch.G,2dc)@C,3dc,"
    "(2dc,2ch.H,2dc)@D,3dc,dc@A,ss"
)


def test_back_to_back_chains_are_one_space_even_if_only_part_is_labelled():
    # "ch 2, ch 2" between two stitches is one space: working into the label works all of it
    for chains in ("2ch.A,2ch", "2ch,2ch.A", "4ch.A"):
        base = f"ring.R0\n(dc.S,{chains},dc.T)@R0\n"
        result, rows = rows_of(base + "dc@S,(2dc)@A,dc@T")
        assert rows[2].unworked == 0 and rows[2].overflow == 0, (chains, rows[2])
        assert rows_of(base + "dc@S,dc@T")[1][2].unworked == 1  # the space is still required


def test_two_different_labels_in_one_run_are_two_spaces():
    base = "ring.R0\n(dc.S,2ch.A,2ch.B,dc.T)@R0\n"
    assert rows_of(base + "dc@S,(2dc)@A,(2dc)@B,dc@T")[1][2].unworked == 0
    assert rows_of(base + "dc@S,(2dc)@A,dc@T")[1][2].unworked == 1  # B is a space of its own


def test_round_worked_into_a_space_written_in_two_pieces_is_ok():
    result, rows = rows_of(RING + RING_ROUND_2)
    assert result.ok, result.error
    assert rows[2].unworked == 0 and rows[2].overflow == 0
    # leaving a stitch of that round out is still caught
    short = RING + RING_ROUND_2.replace("@D,3dc", "@D,2dc")
    assert not rows_of(short)[0].ok


# dc square: each round is worked into the corners of the one before, with dc along the sides.
DC_SQUARE = (
    "ring.R0\n2ch,(tr.A,3dc,tr.B,3dc,tr.C,3dc,tr.D,2dc)@R0,ss\n"
    "2ch,(2dc,tr.E,2dc)@A,3dc,(2dc,tr.F,2dc)@B,3dc,(2dc,tr.G,2dc)@C,3dc,(2dc,tr.H,2dc)@D,3dc\n"
)


def dc_square_round(side, corners="EFGH", into="EFGH"):
    a, b, c, d = corners
    w, x, y, z = into
    return (f"2ch,(2dc,tr.{a},2dc)@{w},{side},(2dc,tr.{b},2dc)@{x},{side},"
            f"(2dc,tr.{c},2dc)@{y},{side},(2dc,tr.{d},2dc)@{z},{side}")


def test_sides_worked_only_in_part_leave_stitches_unworked():
    # The sides of round 3 have 7 stitches (2 from each corner and the 3 between). The engine
    # moves on to the next corner's @ after "5dc", so 2 stitches per side are left alone.
    result, rows = rows_of(DC_SQUARE + dc_square_round("5dc", "IJKL"))
    assert not result.ok
    assert result.error.kind == "count" and result.error.row == 3
    assert rows[3].unworked == 8 and rows[3].overflow == 0
    # a round after that one: the sides have 11 stitches
    full = DC_SQUARE + dc_square_round("7dc", "IJKL") + "\n" + dc_square_round("7dc", "MNOP", "IJKL")
    result, rows = rows_of(full)
    assert rows[3].unworked == 0 and rows[3].overflow == 0
    assert not result.ok and result.error.row == 4
    assert rows[4].unworked == 16


def test_last_side_wraps_onto_the_first_stitches_of_the_round():
    # The last side of round 3 ends on the 2 dc the round began with; that is not an overflow.
    result, rows = rows_of(DC_SQUARE + dc_square_round("7dc", "IJKL"))
    assert result.ok, result.error
    assert rows[3].stitch_count == 50
    # one stitch too many on the sides is still an overflow
    result, rows = rows_of(DC_SQUARE + dc_square_round("8dc", "IJKL"))
    assert not result.ok and rows[3].overflow > 0


def test_chain_ring_square_shape_hints():
    from frogless.pipeline.shape import check_shape, corner_sides

    round_3 = (
        "(dc.X,2ch.I,2dc)@E,7dc,(2dc,2ch.J,2dc)@F,7dc,(2dc,2ch.K,2dc)@G,7dc,"
        "(2dc,2ch.L,2dc)@H,7dc,dc@W,ss"
    )
    result, rows = rows_of(RING + RING_ROUND_2 + "\n" + round_3)
    assert result.ok, result.error
    assert [len(corner_sides(rows[i])) for i in (1, 2, 3)] == [4, 4, 4]
    found = check_shape(result.rows, from_ring=True)
    # a square: no circle-growth hint; round 1's last corner is a ch-4 space, the others ch-2
    assert [(f.row, f.kind) for f in found] == [(1, "uneven_corners")]
    assert "one corner is a ch-4 space, the others are ch-2" in found[0].message


def test_a_corner_worked_one_stitch_per_chain_of_a_long_space_is_still_a_corner():
    # round 1's last corner is one ch-4 space; round 2 puts 2dc, ch 2, 2dc into it, one stitch in each chain of it
    from frogless.pipeline.shape import check_shape, corner_sides

    ring = "(4ch,ss@[%,0]).R_1\n(dc.S,2ch.A,3dc,2ch.B,3dc,2ch.C,3dc,4ch.D,2dc)@R_1,ss@S\n"
    round_2 = ("(dc.W,2ch.E,2dc)@A,3dc,(2dc,2ch.F,2dc)@B,3dc,(2dc,2ch.G,2dc)@C,3dc,"
               "(2dc,2ch.H,2dc)@D,3dc,dc,ss@W")
    round_3 = ("(dc.V,2ch.I,2dc)@E,7dc,(2dc,2ch.J,2dc)@F,7dc,(2dc,2ch.K,2dc)@G,7dc,"
               "(2dc,2ch.L,2dc)@H,7dc,dc,ss@V")
    result, rows = rows_of(ring + round_2 + "\n" + round_3)
    assert result.ok, result.error
    assert [len(corner_sides(rows[i])) for i in (1, 2, 3)] == [4, 3, 4]  # the plain graph loses the ch-4 corner
    found = check_shape(result.rows, from_ring=True)
    assert "corners_changed" not in [f.kind for f in found]  # four corners in every round: nothing twists
    assert [(f.row, f.kind) for f in found] == [(1, "uneven_corners")]


# ---- extra chains skipped before a foundation row's first stitch form a space and count ----
def test_only_the_exact_turning_chain_height_is_not_counted_in_a_foundation_row():
    from frogless.engine import get_engine
    from frogless.pipeline.gate import row_counts

    engine = get_engine()

    def counts(code):
        return row_counts(engine.check(code).rows[1], None)

    assert counts("15ch\nsk,14sc")[0] == 14  # Ch 15, sc in 2nd ch
    assert counts("17ch\n3sk,14dc")[0] == 14  # Ch 17, dc in 4th ch (ch 3 is the turning chain)
    assert counts("17ch\n2sk,15dc")[0] == 15  # dc in 3rd ch (ch 2 is the turning chain)
    # Ch 94, sc in 4th ch from hook, [ch 1, skip 1 ch, sc in next ch] across: 46 sc + 46 chains
    assert counts("94ch\n3sk,sc,45*[ch,sk,sc]") == [92, 46]
    assert counts("94ch\n5sk,sc,44*[ch,sk,sc]")[0] == 91  # 4 extra skipped chains: 2 more
    assert row_counts(engine.check("94ch\n3sk,sc,45*[ch,sk,sc]").rows[1], "sc") == [46]  # a typed count is the stitch only


def test_extra_chains_at_the_start_of_any_row_form_a_space_and_count():
    from frogless.engine import get_engine
    from frogless.pipeline.gate import row_counts

    engine = get_engine()
    foundation = "94ch\n3sk,sc,45*[ch,sk,sc]\n"

    def counts(row, stitch=None):
        return row_counts(engine.check(foundation + row).rows[2], stitch)

    # Ch 2, sc in first ch-1 sp, [ch 1, skip 1, sc in next ch-1 sp] across: the last sc goes into the ch-2's second chain
    assert counts("2ch,sc,45*[ch,sk,sc]")[0] == 92
    assert counts("2ch,sc,45*[ch,sk,sc]", "sc") == [46]  # a typed count is still the stitch only
    # the exact turning-chain heights are unchanged
    assert counts("ch,sc,45*[ch,sk,sc]")[0] == 91  # ch 1, sc across
    assert counts("ch,sc,45*[ch,sk,sc]", None)[1] == 46
    dc = engine.check("20ch\n3sk,17dc\n3ch,17dc").rows[2]
    assert row_counts(dc, None)[0] == 17  # ch 3, dc across
    dc2 = engine.check("20ch\n3sk,17dc\n2ch,17dc").rows[2]
    assert row_counts(dc2, None)[0] == 17  # ch 2 also a dc turning chain
    hdc = engine.check("20ch\n2sk,18hdc\n2ch,18hdc").rows[2]
    assert row_counts(hdc, None)[0] == 18  # ch 2, hdc across
    assert row_counts(engine.check("20ch\n3sk,17dc\n4ch,17dc").rows[2], None)[0] == 18  # ch 4, dc: one extra chain
