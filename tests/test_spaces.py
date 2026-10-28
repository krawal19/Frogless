"""Naming chain spaces: `@sp` ("into the next chain space") resolved to generated names."""

import pytest

from frogless.engine import get_engine

SC_MESH = "12ch\nsk,sc,5*[ch,sk,sc],turn\n"  # 6 sc, 5 chain spaces
DC_MESH = "10ch\n3sk,dc,3*[ch,sk,dc],turn\n"  # 4 dc, 3 chain spaces
GRANNY = "14ch\n3sk,3dc,2*[ch,sk,3dc],turn\n"  # three 3-dc groups, 2 chain spaces


def resolve_spaces(code):
    return get_engine().resolve(code)


def rows_of(code):
    result = get_engine().check(code)
    return result, {r.index: r for r in result.rows}


# ---- the naming step on its own ----
def test_code_without_sp_is_untouched():
    code = "12ch\nsk,5*[sc,ch],sc,turn\nch,sc"
    assert resolve_spaces(code) == code


def test_repeats_are_written_out_and_every_space_gets_a_name():
    out = resolve_spaces(SC_MESH + "ch,sk,sc@sp,4*[ch,sk,sc@sp],sc").split("\n")
    assert "*" not in out[1] and "*" not in out[2]
    names = [part.split(".")[1] for part in out[1].split(",") if part.startswith("ch.")]
    assert len(names) == len(set(names)) == 5


def test_after_a_turned_row_the_spaces_are_worked_right_to_left():
    out = resolve_spaces(DC_MESH + "2ch,3*[ch,sk,dc@sp]").split("\n")
    named = [p.split(".")[1] for p in out[1].split(",") if p.startswith("ch.")]
    used = [p.split("@")[1] for p in out[2].split(",") if "@" in p]
    assert used == named[::-1]


def test_after_a_round_the_spaces_are_worked_left_to_right():
    code = "ring.R0\n(4dc)@R0\n4*[dc,ch],ss\n" + "4*[dc@sp,sk]"
    code = "ring.R0\n(4dc)@R0\n4*[dc,ch]\n" + "3*[dc@sp],dc"
    out = resolve_spaces(code).split("\n")
    named = [p.split(".")[1] for p in out[2].split(",") if p.startswith("ch.")]
    used = [p.split("@")[1] for p in out[3].split(",") if "@" in p]
    assert len(named) == 3 and used == named  # the last chain has no stitch after it: not a space


def test_a_label_the_model_wrote_is_kept():
    out = resolve_spaces("12ch\nsk,sc,ch.A,sk,sc,ch,sk,sc,turn\nch,sk,sc@sp,ch,sk,sc@sp").split("\n")
    assert "ch.A" in out[1]
    assert out[2].split(",")[-1].endswith("@A")


def test_back_to_back_chains_are_one_space():
    out = resolve_spaces("12ch\nsk,sc,ch,ch,sk,sc,ch,sk,sc,turn\nch,sk,sc@sp,sk,sc@sp").split("\n")
    assert len(set(p.split("@")[1] for p in out[2].split(",") if "@" in p)) == 2
    with pytest.raises(ValueError):  # two spaces below, not three
        resolve_spaces("12ch\nsk,sc,ch,ch,sk,sc,ch,sk,sc,turn\nsc@sp,sc@sp,sc@sp")


def test_turning_chains_at_the_ends_of_a_row_are_not_spaces():
    with pytest.raises(ValueError):
        resolve_spaces("12ch\n2ch,sc,sc,sc,2ch,turn\nsc@sp")


def test_more_spaces_than_the_row_below_has_is_an_error():
    with pytest.raises(ValueError):
        resolve_spaces(SC_MESH + "ch,sk,sc@sp,5*[ch,sk,sc@sp]")


def test_sp_on_the_first_line_is_an_error():
    with pytest.raises(ValueError):
        resolve_spaces("dc@sp,dc@sp")


def test_a_long_repeat_gets_a_name_per_space():
    n = 45
    code = f"{2 * n + 3}ch\n3sk,dc,{n}*[ch,sk,dc],turn\n2ch,{n}*[ch,sk,dc@sp],sk,dc"
    out = resolve_spaces(code).split("\n")
    names = [p.split(".")[1] for p in out[1].split(",") if p.startswith("ch.")]
    used = [p.split("@")[1] for p in out[2].split(",") if "@" in p]
    assert len(set(names)) == n and used == names[::-1]


# ---- with the engine ----
def test_sc_mesh_working_every_space_is_ok():
    result, rows = rows_of(SC_MESH + "ch,sk,sc@sp,4*[ch,sk,sc@sp],sc")
    assert result.ok, result.error
    assert [rows[i].stitch_types["sc"] for i in (1, 2)] == [6, 6]
    assert rows[2].unworked == 0 and rows[2].overflow == 0


def test_sc_mesh_that_skips_a_space_reports_it_unworked():
    result, rows = rows_of(SC_MESH + "ch,sk,sc@sp,3*[ch,sk,sc@sp],sc")
    assert not result.ok and result.error.kind == "count" and result.error.row == 2
    assert rows[2].unworked >= 1


def test_skipping_a_space_on_purpose_with_sk_is_fine():
    result, _ = rows_of(SC_MESH + "ch,sk,sc@sp,ch,sk,sk@sp,3*[ch,sk,sc@sp],sc")
    assert result.ok, result.error


def test_dc_mesh_ending_in_the_turning_chain_of_the_row_below():
    code = DC_MESH + "2ch,3*[ch,sk,dc@sp],sk,dc,turn\n2ch,2*[ch,sk,dc@sp],sk,dc"
    result, rows = rows_of(code)
    assert rows[2].unworked == 0 and rows[2].overflow == 0
    assert [rows[i].stitch_types["dc"] for i in (1, 2)] == [4, 4]
    result, _ = rows_of(DC_MESH + "2ch,3*[ch,sk,dc@sp],sk,dc")
    assert result.ok, result.error


def test_granny_stripe_groups_in_each_space():
    result, rows = rows_of(GRANNY + "3ch,3sk,dc3inc@sp,ch,dc3inc@sp,3sk,dc")
    assert result.ok, result.error
    assert rows[2].unworked == 0 and rows[2].overflow == 0


def test_granny_stripe_that_misses_a_space_is_reported():
    result, rows = rows_of(GRANNY + "3ch,3sk,dc3inc@sp,ch,3sk,dc")
    assert not result.ok and result.error.row == 2
    assert rows[2].unworked >= 1


def test_too_many_sp_is_an_invalid_line_not_a_crash():
    result, _ = rows_of(SC_MESH + "ch,sk,sc@sp,5*[ch,sk,sc@sp],sc")
    assert not result.ok and result.error.kind == "invalid"
    assert "chain spaces" in result.error.message


def test_describe_reads_sp_in_words():
    text = " ".join(get_engine().describe(SC_MESH + "ch,sk,sc@sp,ch,sk,sk@sp"))
    assert "next chain space" in text and "skip next chain space" in text
