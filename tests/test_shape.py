"""Shape hints, from hand-made rows (no engine needed)."""

from frogless.engine import RowInfo, StitchInfo
from frogless.pipeline.shape import (
    check_chain_ring_start,
    check_circle_growth,
    check_even_spacing,
    check_flat_rows,
    check_polygon,
    check_shape,
    corner_sides,
    meant_flat,
    starts_from_ring,
)


def rounds(counts, stitch="sc"):
    """Rounds from a ring with the given stitch counts, round 1 first."""
    return [RowInfo(i + 1, c, {stitch: c}) for i, c in enumerate(counts)]


def kinds(finds):
    return [f.kind for f in finds]


def stitch_row(index, kind_list, count=None, **kw):
    """A row made of the given stitch kinds, each worked into its own place in the row below."""
    stitches = [StitchInfo(i, k, [(index - 1, i)]) for i, k in enumerate(kind_list)]
    n = count if count is not None else sum(int(k[2:-3] or 2) if k.endswith("inc") else 1 for k in kind_list)
    return RowInfo(index, n, {}, stitches=stitches, **kw)


# ---- 1. circle growth -----------------------------------------------------------------------


def test_flat_sc_circle_lies_flat():
    found = check_circle_growth(rounds([6, 12, 18, 24]))
    assert kinds(found) == ["flat_circle"]
    assert found[0].severity == "info" and "lie flat" in found[0].message


def test_dc_circle_uses_taller_growth():
    assert kinds(check_circle_growth(rounds([12, 24, 36], "dc"))) == ["flat_circle"]
    assert kinds(check_circle_growth(rounds([6, 12, 18], "dc")))[:1] == ["cups"]


def test_even_rounds_cup():
    found = check_circle_growth(rounds([6, 6, 6, 6]))
    assert kinds(found) == ["cups"] and found[0].severity == "warning"
    assert "tube or cup" in found[0].message


def test_too_few_increases_cups_a_bowl():
    found = check_circle_growth(rounds([6, 9, 12]))
    assert kinds(found) == ["cups", "cups"] and "bowl" in found[0].message


def test_doubling_ruffles():
    found = check_circle_growth(rounds([6, 12, 24, 48]))
    assert kinds(found) == ["ruffles", "ruffles"] and "ruffle" in found[0].message


def test_ball_is_not_a_warning():
    found = check_circle_growth(rounds([6, 12, 18, 18, 18, 12, 6]))
    assert kinds(found) == ["flat_circle", "ball"]
    assert all(f.severity == "info" for f in found) and "ball" in found[1].message


def test_flat_base_then_straight_sides_is_a_tube():
    found = check_circle_growth(rounds([6, 12, 18, 18, 18]))
    assert kinds(found) == ["flat_circle", "tube"]
    assert all(f.severity == "info" for f in found)


def test_one_even_round_inside_growth_is_fine():
    assert kinds(check_circle_growth(rounds([6, 12, 12, 18]))) == ["flat_circle"]


# ---- 2. even spacing ------------------------------------------------------------------------


def spaced_row(inc_at, length=24):
    return stitch_row(4, ["sc2inc" if i in inc_at else "sc" for i in range(length)])


def test_bunched_increases_warn():
    found = check_even_spacing([spaced_row({0, 2, 4, 6, 8, 10})], cyclic=True)
    assert kinds(found) == ["uneven_increases"]
    assert "Round 4's increases are bunched" in found[0].message and "2, 2, 2, 2, 2, 14" in found[0].message


def test_even_increases_do_not_warn():
    assert check_even_spacing([spaced_row({0, 4, 8, 12, 16, 20})], cyclic=True) == []


def test_staggered_start_and_off_by_one_gap_do_not_warn():
    assert check_even_spacing([spaced_row({0, 4, 8, 12, 16, 20}, length=25)], cyclic=True) == []


def test_bunched_decreases_warn():
    row = stitch_row(5, ["sc2tog" if i in (0, 1, 2, 10) else "sc" for i in range(18)])
    assert kinds(check_even_spacing([row], cyclic=True)) == ["uneven_decreases"]


def test_spacing_needs_stitch_info_and_three_changes():
    assert check_even_spacing(rounds([6, 12]), cyclic=True) == []
    assert check_even_spacing([spaced_row({0, 1})], cyclic=True) == []


# ---- 3. squares and polygons ----------------------------------------------------------------


def corner_round(index, sides, wrap=False, chains=None, types=None):
    """A round of corner groups (dc, ch..., dc into the same place) joined by plain sides.
    chains gives the chains in each corner space (default 1); types the row's stitch_types."""
    kind_into: list[tuple[str, list]] = []
    for c, length in enumerate(sides):
        place = (index - 1, 100 + c)
        kind_into += [("dc", [place])] + [("ch", [])] * (chains[c] if chains else 1) + [("dc", [place])]
        kind_into += [("dc", [(index - 1, 10 * c + j)]) for j in range(length)]
    if wrap:  # start with the corner's second half, end with its first half and the chain
        kind_into = kind_into[2:] + kind_into[:2]
    stitches = [StitchInfo(i, k, into) for i, (k, into) in enumerate(kind_into)]
    return RowInfo(index, sum(k != "ch" for k, _ in kind_into), types or {}, stitches=stitches)


def test_square_with_equal_sides_is_quiet():
    row = corner_round(4, [15, 15, 15, 15])
    assert corner_sides(row) == [15, 15, 15, 15]
    assert check_polygon([row]) == []
    assert check_shape([row]) == []


def test_corner_at_the_end_of_the_round_wraps():
    row = corner_round(4, [7, 7, 7, 7], wrap=True)
    assert sorted(corner_sides(row)) == [7, 7, 7, 7]
    assert check_polygon([row]) == []


def test_one_long_side_warns():
    found = check_polygon([corner_round(4, [15, 15, 15, 19])])
    assert kinds(found) == ["uneven_sides"]
    assert "Round 4: sides have 15, 15, 15, 19 stitches" in found[0].message


def test_rectangle_with_matching_opposite_sides_is_quiet():
    assert check_polygon([corner_round(4, [10, 4, 10, 4])]) == []


def test_corners_changing_warns():
    found = check_polygon([corner_round(3, [9, 9, 9, 9]), corner_round(4, [12, 12, 12])])
    assert kinds(found) == ["corners_changed"]
    assert found[0].row == 4 and "3 corners" in found[0].message and "had 4" in found[0].message


def test_labelled_corners_count_without_chains():
    items = []
    for c in range(4):
        items += [StitchInfo(len(items), "dc", [(0, c)], "corner") for _ in range(3)]
        items += [StitchInfo(len(items), "dc", [(0, 50 + 5 * c + j)]) for j in range(5)]
    assert corner_sides(RowInfo(2, len(items), {}, stitches=items)) == [5, 5, 5, 5]


def test_uneven_corner_spaces_warn():
    row = corner_round(1, [3, 3, 3, 3], chains=[2, 2, 2, 4])
    found = check_polygon([row])
    assert kinds(found) == ["uneven_corners"]
    assert found[0].message.startswith("Round 1: one corner is a ch-4 space, the others are ch-2.")
    assert check_polygon([corner_round(1, [3, 3, 3, 3], chains=[2, 2, 2, 2])]) == []
    # more than one odd corner: list them
    found = check_polygon([corner_round(1, [3, 3, 3, 3], chains=[2, 3, 2, 4])])
    assert "differ in size (ch-2, ch-3, ch-2, ch-4)" in found[0].message


def test_round_without_chains_has_no_corners():
    assert corner_sides(spaced_row({0, 4})) == []


# ---- 4. flat rows ---------------------------------------------------------------------------


def test_row_drift_without_explanation_warns():
    below = stitch_row(1, ["sc"] * 10)
    found = check_flat_rows([below, stitch_row(2, ["sc"] * 12)])
    assert kinds(found) == ["count_drift"] and "10" in found[0].message


def test_row_with_increase_or_decrease_is_explained():
    below = stitch_row(1, ["sc"] * 10)
    assert check_flat_rows([below, stitch_row(2, ["sc"] * 9 + ["sc2inc"])]) == []
    assert check_flat_rows([below, stitch_row(2, ["sc"] * 8 + ["sc2tog"], count=9)]) == []


# ---- the whole thing ------------------------------------------------------------------------


def test_check_shape_circle_needs_the_ring_flag():
    assert kinds(check_shape(rounds([6, 6, 6]))) == []
    assert kinds(check_shape(rounds([6, 6, 6]), from_ring=True)) == ["cups"]


def test_starts_from_ring():
    assert starts_from_ring("Round 1: 6 sc in a magic ring")
    assert starts_from_ring("ch 2, 6 sc in the first ch")
    assert not starts_from_ring("ch 21, sc in 2nd ch")  # a flat foundation chain


# ---- squares are not circles; chains do not count as growth -----------------------------------


def square_rounds(n=3, dc_per_side=3):
    """Chain-ring square: corner spaces of 2 chains, sides growing by 2 dc per round, 8 a round."""
    rows = []
    for k in range(n):
        side = dc_per_side + 2 * k
        types = {"dc": 4 * (side + 2), "ch": 8, "ss": 1}
        rows.append(corner_round(k + 1, [side] * 4, chains=[2] * 4, types=types))
    return rows


def test_square_rounds_skip_the_circle_check():
    rows = square_rounds()
    assert [len(corner_sides(r)) for r in rows] == [4, 4, 4]
    assert check_circle_growth(rows) == []
    assert check_shape(rows, from_ring=True) == []
    # the same stitch counts without corners are judged as a circle
    assert kinds(check_circle_growth(rounds([20, 28, 36], "dc"))) == ["flat_circle"]


def test_growth_leaves_out_chains_and_slip_stitches():
    rows = [
        RowInfo(1, 20, {"sc": 6, "ch": 13, "ss": 1}),
        RowInfo(2, 14, {"sc": 12, "ch": 2}),
        RowInfo(3, 19, {"sc": 18, "ss": 1}),
    ]
    found = check_circle_growth(rows)
    assert kinds(found) == ["flat_circle"] and "grow by 6, 6" in found[0].message
    # a ring of chains before the first round is not a round
    ring = RowInfo(0, 5, {"ch": 4, "ss": 1})
    again = check_circle_growth([ring] + rounds([6, 12, 18]))
    assert kinds(again) == ["flat_circle"]


# ---- flat pieces vs 3D pieces -----------------------------------------------------------------


def test_meant_flat_reads_the_pattern():
    assert meant_flat("Coaster. Round 1: 6 sc in a magic ring")
    assert meant_flat("Work until the circle lies flat")
    assert not meant_flat("Strawberry. Round 1: 6 sc in a magic ring")


def test_growth_is_a_warning_only_for_a_flat_piece():
    cone = rounds([6, 9, 12, 15, 18])  # grows by 3: cups
    flat = check_shape(cone, from_ring=True, flat=True)
    assert [f.severity for f in flat if f.kind == "cups"] == ["warning"] * 4
    shaped = [f for f in check_shape(cone, from_ring=True, flat=False) if f.kind == "cups"]
    assert len(shaped) == 1 and shaped[0].severity == "info" and "Rounds 2-5" in shaped[0].message


# ---- 5/6. stacked increases and chain ring start --------------------------------------------


def stacked_rounds(shift):
    """Round 1 is 6 sc; rounds 2-5 each have 6 increases (sc2inc) after a growing run of sc.
    `shift` moves where every round's increases sit."""
    rows_ = [RowInfo(1, 6, {"sc": 6})]
    for r in range(2, 6):
        seg = r - 1  # plain sc between increases, so each segment is seg + 1 stitches
        size = 6 * (seg + 1)
        spots = {(seg + (r - 2) * shift + (seg + 1) * k) % size for k in range(6)}
        rows_.append(stitch_row(r, ["sc2inc" if i in spots else "sc" for i in range(size)]))
    return rows_


def test_stacked_increases_hint():
    hit = [f for f in check_shape(stacked_rounds(0), from_ring=True) if f.kind == "stacked_increases"]
    assert hit and hit[0].severity == "info" and "hexagon" in hit[0].message


def test_staggered_increases_no_hint():
    assert "stacked_increases" not in kinds(check_shape(stacked_rounds(2), from_ring=True))


def test_ball_gets_no_stacked_hint():
    rows_ = stacked_rounds(0) + [RowInfo(6, 30, {"sc": 30}), RowInfo(7, 24, {"sc": 24})]
    assert "stacked_increases" not in kinds(check_shape(rows_, from_ring=True))


BALL = rounds([6, 12, 18, 18, 12, 6])


def test_chain_ring_amigurumi_hint():
    found = check_shape(BALL, from_ring=True, text="Ch 2, 6 sc in 2nd ch from hook.")
    assert kinds(found).count("chain_ring_start") == 1
    assert "chain_ring_start" in kinds(check_shape(rounds([6, 12]), from_ring=True,
                                                    text="Ch 4, sl st to form a ring. Stuff firmly."))


def test_magic_ring_no_chain_ring_hint():
    assert "chain_ring_start" not in kinds(check_shape(BALL, from_ring=True, text="Magic ring, 6 sc in ring. Stuff."))


def test_granny_square_chain_ring_no_hint():
    text = "Granny square. Ch 4, sl st to form a ring."
    assert check_chain_ring_start(BALL, text, []) == []
    assert "chain_ring_start" not in kinds(check_shape(BALL, from_ring=True, flat=True, text=text))


def test_an_oval_gets_no_even_spacing_hint():
    from frogless.engine import get_engine
    from frogless.pipeline.shape import check_shape

    oval = ("Ch 13\nR1: sc in 2nd ch from hook, sc in next 10 ch, 3 sc in last ch, rotate, sc in next 10 ch, "
            "2 sc in last ch (26)\nR2: inc, 10 sc, inc x3, 10 sc, inc x2 (32)")
    rows = get_engine().check("13ch.A\nsk,11sc,sc3inc,(10sc,sc2inc)@A\nsc2inc,10sc,3*[sc2inc],10sc,2*[sc2inc]").rows
    assert not [f for f in check_shape(rows, oval=True, text=oval) if f.kind.startswith("uneven_") and "bunched" in f.message]
    assert [f for f in check_shape(rows, text=oval) if "bunched" in f.message]  # without the flag the hint shows
