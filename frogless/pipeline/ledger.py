"""Step 4: the stitch ledger. Check by counting the rows the engine cannot model.

Some rows cannot be written in the engine's code (legs worked back along a chain, spike stitches into
lower rows, two pieces joined together), so the translator answers "# CANNOT". A crocheter still checks
such a row by counting. The ledger does the same: the model READS the row (what it works into, what it
makes) and our code does the ARITHMETIC. Nothing the model says is taken on trust:
- every quote it gives must be a part of the row's text, or the whole answer is rejected;
- the stitches the row works into must be the stitches the row below made (the engine's count for rows
  it modelled, the ledger's count for ledger rows);
- the stitches the row makes must fit the total the row states.

Which rows: every non-synthetic row from the first "cannot" row on. Once a row is not modelled, the
engine no longer knows the row below the next one, so each later row is counted too, in order. If the
pattern already breaks (or cannot be checked) before the first of them, nothing is asked.

A mismatch is a break (ledger_ok False). An answer that is invalid or has a quote the row does not contain
is rejected: that row stays unreadable and no later row is asked.
"""

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

from ..engine import Engine
from ..models.client import ROOT
from ..patterns.stated import stated_count
from .report import RowResult
from .translate import ask_cached
from .verdict import decide_verdict

ROLE = "ledger"
PROMPT = ROOT / "frogless" / "prompts" / "ledger_row.md"
CACHE_DIR = ROOT / "logs" / "cache" / "ledger_row"
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "uses": {"type": "integer"},
        "makes": {"type": "integer"},
        "skips": {"type": "integer"},
        "quotes": {"type": "array", "items": {"type": "string"}},
        "explanation": {"type": "string"},
    },
    "required": ["uses", "makes", "skips", "quotes", "explanation"],
    "additionalProperties": False,
}

_LABEL = re.compile(r"^\s*(?:rows?|rnds?|rounds?|r)\s*[\d\s\-–,&and]*:\s*", re.IGNORECASE)
_JOINS = re.compile(r"\b(?:together|join(?:ed|ing)?|both|two pieces|each other)\b", re.IGNORECASE)
_LEAVES = re.compile(r"\b(?:unworked|leave|left|do not work|don't work|not work|remaining|rest of)\b", re.IGNORECASE)
_FRESH = re.compile(r"^\W*(?:make\s+(?:a\s+|an\s+)?)?(?:magic\s+(?:ring|circle)|foundation|ch(?:ain)?\s*\d+)",
                    re.IGNORECASE)


@dataclass
class Answer:
    uses: int
    makes: int
    skips: int
    quotes: list[str]
    explanation: str


def _squash(text: str) -> str:
    return " ".join(text.lower().split())


def read_answer(text: str, source: str) -> Answer | str:
    """The model's reply as an Answer, or the reason it is rejected (a string)."""
    try:
        raw = json.loads(text)
        numbers = [raw["uses"], raw["makes"], raw["skips"]]
        quotes = [q for q in raw["quotes"]]
        explanation = str(raw["explanation"]).strip()
    except (ValueError, KeyError, TypeError):
        return "the reply was not valid"
    if any(isinstance(n, bool) or not isinstance(n, int) or n < 0 for n in numbers):
        return "the counts were not whole numbers"
    if not all(isinstance(q, str) and q.strip() for q in quotes):
        return "a quote was empty"
    uses, makes, skips = numbers
    if skips > uses:
        return "it skips more stitches than it works into"
    if (uses or makes) and not quotes:
        return "it quoted nothing from the row"
    haystack = _squash(source)
    for q in quotes:
        if _squash(q) not in haystack:
            return f"the quote '{q.strip()[:60]}' is not in the row"
    return Answer(uses, makes, skips, [q.strip() for q in quotes], explanation)


def judge(source: str, a: Answer, below: list[int] | None) -> tuple[str, list[int] | None]:
    """Check an accepted answer's arithmetic. Returns (what does not fit, "" if it all fits; the
    counts the row below the NEXT row may have: what this row made)."""
    if a.uses == 0 and a.makes == 0:  # not a stitch row (finishing off, a note): nothing changes
        return "", below
    stated = stated_count(source)
    if stated is not None and (stated.multi_size or stated.stitch):  # a count of one stitch type is not a total
        stated = None
    if stated is not None and stated.count != a.makes:
        return f"the pattern says {stated.count}, but the instructions make {a.makes}", [a.makes]
    if below is not None and not _uses_fit(source, a.uses, below):
        want = max(below)
        return f"the row works into {a.uses} stitches of the row below, which has {want}", [a.makes]
    return "", [a.makes]


def _uses_fit(source: str, uses: int, below: list[int]) -> bool:
    if uses in below:
        return True
    if uses == 0:  # a fresh start: a magic ring or a foundation chain
        return bool(_FRESH.match(_LABEL.sub("", source.strip(), count=1)))
    if uses in [2 * b for b in below]:  # two pieces joined together
        return bool(_JOINS.search(source))
    if uses < max(below):  # stitches left unworked on purpose
        return bool(_LEAVES.search(source))
    return False


def ledger_positions(rows: list[RowResult]) -> list[int]:
    """Positions of the rows to count: the first "cannot" row and every written row after it."""
    first = next((i for i, r in enumerate(rows) if r.status == "cannot" and not r.synthetic), None)
    if first is None:
        return []
    return [i for i in range(first, len(rows)) if not rows[i].synthetic]


def _row_below(engine: Engine, text: str, prefix: list[RowResult]) -> tuple[bool, list[int] | None]:
    """(whether the rows before the first ledger row check out, the counts the row below may have).

    The counts are None when there is no row below to compare with (a pattern that starts with the
    unusual row); a foundation chain allows for the chains a first row skips.
    """
    if not any(r.code for r in prefix):
        return True, None
    check = engine.check("\n".join(r.code for r in prefix if r.code))
    verdict, _, computed = decide_verdict(engine, text, prefix, check)
    if verdict.kind not in ("works", "works_unverified"):
        return False, None
    if check.rows and check.rows[-1].index == 0:
        chain = check.rows[-1].stitch_count
        return True, list(range(max(chain - 4, 1), chain + 1))
    return True, [computed[max(computed)]] if computed else None


def _ask(text: str, row: RowResult, cache_dir: Path) -> tuple[Answer | str, float]:
    prompt = PROMPT.read_text(encoding="utf-8").format(original=text.strip(), index=row.index, source=row.source)
    reply, cost = ask_cached(prompt, ROLE, ANSWER_SCHEMA, cache_dir, "ledger_row")
    if not reply["text"].strip():
        return "the model gave no answer", cost
    return read_answer(reply["text"], row.source), cost


def count_ledger(engine: Engine, text: str, rows: list[RowResult],
                 cache_dir: Path = CACHE_DIR) -> tuple[list[RowResult], float]:
    """Count every row the engine cannot model and fill the ledger_* fields of those rows.

    Returns (rows, cost in USD); cached replies cost nothing. A counted row has its engine code
    cleared: the engine never sees it.
    """
    rows, total = list(rows), 0.0
    todo = ledger_positions(rows)
    if not todo:
        return rows, total
    ok, below = _row_below(engine, text, rows[:todo[0]])
    if not ok:  # the pattern already breaks (or is unreadable) before the first such row
        return rows, total
    seen: dict[str, Answer] = {}  # a range of rows ("Rounds 8-14") shares one answer
    done = 0
    for pos in todo:
        row = rows[pos]
        answer = seen.get(row.source)
        if answer is None:
            answer, cost = _ask(text, row, cache_dir)
            total += cost
        if isinstance(answer, str):
            rows[pos] = replace(row, code="", status="cannot", ledger_note=f"the AI's count was rejected: {answer}",
                                note=row.note if row.status == "cannot" else "it follows rows that could not be read")
            break
        seen[row.source] = answer
        problem, below = judge(row.source, answer, below)
        rows[pos] = replace(row, code="", ledger_uses=answer.uses, ledger_makes=answer.makes,
                            ledger_ok=not problem, ledger_note=problem or answer.explanation)
        done = pos
        if problem:
            break
    for pos in range(todo[0], done):  # markers between counted rows (fasten off ...) model nothing
        if rows[pos].synthetic:
            rows[pos] = replace(rows[pos], code="")
    return rows, total
