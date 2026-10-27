"""Keeps the model-facing notation guide honest: every example and stitch name must pass the engine."""

import re

import pytest

from frogless.engine import get_engine

GUIDE = get_engine().notation_guide()

EXAMPLE_RE = re.compile(
    r"```english\n(?P<english>.*?)```\s*"
    r"```code\n(?P<code>.*?)```\s*"
    r"```counts\n(?P<counts>.*?)```",
    re.S,
)
EXAMPLES = [
    (m["english"].strip(), m["code"].strip(), [int(n) for n in m["counts"].split()])
    for m in EXAMPLE_RE.finditer(GUIDE)
]
STITCH_BLOCK = re.search(r"```stitches\n(.*?)```", GUIDE, re.S)
GUIDE_STITCHES = STITCH_BLOCK.group(1).split() if STITCH_BLOCK else []

# Names that cannot stand alone in a row get a minimal context to be checked in.
CONTEXT = {
    "sk": "20ch\nsk,sc",
    "ring": "ring.R0\n(6sc)@R0",
    "turn": "20ch\nsc,turn",
}
# Words the guide says are invalid; the engine must keep rejecting them.
NOT_VALID = ["inc", "dec", "invdec", "sl", "slst", "blo", "flo", "bobble", "puff", "popcorn", "picot"]
NOT_COUNTED = {"ch", "ss", "sk"}


def test_guide_has_examples_and_stitches():
    assert len(EXAMPLES) >= 6
    assert len(GUIDE_STITCHES) > 20


@pytest.mark.parametrize("english,code,counts", EXAMPLES, ids=[f"ex{i + 1}" for i in range(len(EXAMPLES))])
def test_example_code_is_valid_with_stated_counts(english, code, counts):
    assert "```" not in code
    result = get_engine().check(code)
    assert result.ok, f"{result.error}\n{code}"
    got = []
    for row in result.rows:
        n = sum(c for t, c in row.stitch_types.items() if t not in NOT_COUNTED)
        if n:
            got.append(n)
    assert got == counts, f"{english}\n{code}"


@pytest.mark.parametrize("name", GUIDE_STITCHES)
def test_listed_stitch_is_accepted(name):
    code = CONTEXT.get(name, f"20ch\nsc,{name}")
    result = get_engine().check(code)
    assert result.error is None or result.error.kind != "invalid", f"{name}: {result.error}"


def test_guide_lists_every_stitch_the_translator_knows():
    missing = set(get_engine().stitches()) - set(GUIDE_STITCHES)
    assert not missing, f"guide is missing translator stitches: {missing}"


@pytest.mark.parametrize("name", NOT_VALID)
def test_names_the_guide_calls_invalid_are_rejected(name):
    result = get_engine().check(f"20ch\nsc,{name}")
    assert not result.ok and result.error.kind == "invalid"
    assert name not in GUIDE_STITCHES
