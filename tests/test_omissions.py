"""The omission check: a rules translation that leaves out an item the row's text names is flagged."""

from frogless.engine import get_engine
from frogless.pipeline.gate import gate_translation
from frogless.pipeline.omissions import left_out_item
from frogless.testset.generators import base_cases, load_config
from frogless.testset.inject import injected_cases

RING = "Rnd 1: 6 sc in magic ring (6)\nRnd 2: 2 sc in each st (12)\n"


def line_of(text, n=-1):
    engine = get_engine()
    return engine, [l for l in engine.translate(text).lines if not l.synthetic][n]


def test_a_dropped_trailing_stitch_is_found():
    engine, line = line_of(RING + "Rnd 3: (sc, 2 sc in next st) 6 times, sc (18)")
    assert line.code == "6*[sc,sc2inc]"
    assert left_out_item(engine, line.source, line.code) == "sc"


def test_gate_flags_the_row_with_a_reason():
    engine = get_engine()
    text = RING + "Rnd 3: (sc, 2 sc in next st) 6 times, sc (18)"
    gated = gate_translation(engine, engine.translate(text), text)
    row = [l for l in gated.lines if not l.synthetic][-1]
    assert not row.parsed
    assert row.reason == "the translation leaves out part of the row: 'sc'"


def test_complete_rows_are_not_flagged():
    engine = get_engine()
    for text in (RING + "Rnd 3: (sc, 2 sc in next st) 6 times (18)",
                 RING + "Rnd 3: (sc, 2 sc in next st) 6 times, turn (18)",
                 RING + "Rnd 3: sc in each st around (12)"):
        for line in engine.translate(text).lines:
            if line.parsed and not line.synthetic:
                assert left_out_item(engine, line.source, line.code) == "", line.source


def test_only_the_planted_extra_stitch_is_flagged_in_the_synthetic_cases():
    cfg, engine = load_config(), get_engine()
    bases = base_cases(cfg)
    flagged = []
    for case in bases + injected_cases(cfg, bases):
        for line in engine.translate(case["english"]).lines:
            if line.parsed and not line.synthetic and left_out_item(engine, line.source, line.code):
                flagged.append(case["id"])
    assert flagged and all("extra_stitch" in f for f in flagged), flagged
