"""Test bench tests: specs, generators and injections. A few cases run through the real engine."""

import random

from frogless.engine import get_engine
from frogless.testset.generators import base_cases, load_config
from frogless.testset.inject import TYPES, inject, injected_cases
from frogless.testset.spec import Item, Repeat, Spec, consumed, made

CFG = load_config()
BASES = base_cases(CFG)
BY_ID = {c["id"]: c for c in BASES}


def counts_of(result):
    return [r.stitch_count - r.stitch_types.get("ch", 0) for r in result.rows if r.index >= 1]


def test_arithmetic_helpers():
    row = [Repeat([Item("st", "sc"), Item("inc", "sc")], 6)]
    assert (consumed(row), made(row)) == (12, 18)
    assert (consumed([Item("dec", "sc", 6)]), made([Item("dec", "sc", 6)])) == (12, 6)


def test_generators_make_valid_working_specs():
    assert len(BASES) >= 30
    for case in BASES:
        spec, exp = case["spec"], case["expected"]
        assert isinstance(spec, Spec) and spec.rows
        assert exp == {"verdict": "works", "break_row": None, "counts": [made(r) for r in spec.rows]}
        assert case["english"].count("\n") >= len(spec.rows) // 3  # ranges can merge lines
    assert {c["family"] for c in BASES} == {"circle", "ball", "rows", "rows_hdc", "rows_dc"}


def test_circle_counts_follow_arithmetic():
    assert BY_ID["circle-sc-5r"]["expected"]["counts"] == [6, 12, 18, 24, 30]
    assert BY_ID["circle-dc-4r"]["expected"]["counts"] == [12, 24, 36, 48]
    assert BY_ID["ball-peak18-even1"]["expected"]["counts"] == [6, 12, 18, 18, 12, 6]


def test_english_is_deterministic_and_varied():
    assert [c["english"] for c in base_cases(CFG)] == [c["english"] for c in BASES]
    assert len({str(c["style"]) for c in BASES}) > 10  # phrasing varies between cases


def test_encode_then_check_gives_expected_counts():
    engine = get_engine()
    for case_id in ("circle-sc-5r", "ball-peak18-even1", "rows-10x10"):
        case = BY_ID[case_id]
        result = engine.check(engine.encode(case["spec"]))
        assert result.ok, result.error
        assert counts_of(result) == case["expected"]["counts"]


def test_each_injection_flips_the_verdict_to_the_expected_row():
    engine = get_engine()
    base = BY_ID["circle-sc-6r"]
    for kind in TYPES:
        case = inject(base, kind, random.Random(1))
        assert case and case["injection"] == kind
        assert case["expected"]["verdict"] == "breaks" and case["expected"]["break_row"] >= 2
        if case["known_gap"]:  # the engine may report these a row late or not at all
            continue
        result = engine.check(engine.encode(case["spec"]))
        assert not result.ok and result.error.row == case["expected"]["break_row"], kind


def test_missing_round_is_removed_from_spec_and_english():
    base = BY_ID["circle-sc-6r"]
    case = inject(base, "missing_round", random.Random(1))
    assert len(case["spec"].rows) == len(base["spec"].rows) - 1
    assert case["english"].count("\n") == base["english"].count("\n") - 1


def test_wrong_count_keeps_the_original_stated_count():
    case = inject(BY_ID["circle-sc-6r"], "extra_stitch", random.Random(1))
    r = case["expected"]["break_row"]
    assert case["stated"][r - 1] == BY_ID["circle-sc-6r"]["stated"][r - 1]
    assert case["expected"]["counts"][r - 1] == case["stated"][r - 1] + 1


def test_counted_turning_chain_is_left_out_of_partial_rows():
    # "ch 2, hdc in next 7 sts" makes 8: the ch 2 is the row's first stitch
    case = next(c for c in injected_cases(CFG, BASES) if c["id"].startswith("rows-hdc") and c["injection"] == "missing_stitch")
    r = case["expected"]["break_row"]
    row = case["english"].splitlines()[r]  # line 0 is the foundation chain
    assert f"in next {case['expected']['counts'][r - 1] - 1} sts" in row


def test_known_gap_tags_and_case_total():
    cases = injected_cases(CFG, BASES)
    assert len(BASES) + len(cases) >= 30
    assert {c["injection"] for c in cases} == set(TYPES)
    assert all(c["known_gap"] for c in cases if c["injection"] == "extra_inc")
