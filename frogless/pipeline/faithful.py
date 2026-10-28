"""Step 2: check each row's code says what the pattern says.

Code -> English via the engine's describe(), then a model compares it with the original
row (one call per row). On a mismatch the row is translated again, told what was wrong; after
three translation attempts in all, the row is marked unreadable rather than guessed at.

Which rows: every row the model translated, and rule rows that state no count (the stated-count
gate vouches for rows that do). A mismatching rule row goes to the model translator once.
"""

import json
from dataclasses import replace
from pathlib import Path

from ..engine import Engine
from ..models.client import ROOT
from ..patterns.stated import stated_count
from .report import RowResult
from .translate import CACHE_DIR as TRANSLATE_CACHE_DIR
from .translate import ask_cached, retranslate_row

ROLE = "faithfulness"
PROMPT = ROOT / "frogless" / "prompts" / "faithful_row.md"
CACHE_DIR = ROOT / "logs" / "cache" / "faithful_row"
MAX_ATTEMPTS = 3  # translations of one row, the first included
VERDICTS = ["faithful", "interpreted", "mismatch", "cannot_tell"]
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": VERDICTS},
        "reading": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "reading", "reason"],
    "additionalProperties": False,
}
_UNSUPPORTED_NOTE = (
    'Some lines of the English start with "UNSUPPORTED": the program could not put that part '
    "into words. Judge what you can; if the unsupported part decides the answer, say cannot_tell.\n")


def _needs_check(row: RowResult) -> bool:
    if row.synthetic or row.status != "ok" or not row.code:
        return False
    return row.origin == "model" or stated_count(row.source) is None


def _english(engine: Engine, rows: list[RowResult], i: int) -> list[str]:
    """The English for row i's code. Described after the rows before it, so that labels and
    attachments to earlier stitches read right; only this row's own sentences are returned."""
    own = len(engine.describe(rows[i].code))
    before = [r.code for r in rows[:i] if r.code]
    try:
        lines = engine.describe("\n".join(before + [rows[i].code]))
    except Exception:  # earlier rows we cannot make sense of: describe this row alone
        lines = []
    return lines[-own:] if len(lines) >= own else engine.describe(rows[i].code)


def _judge(guide: str, text: str, row: RowResult, english: list[str], cache_dir: Path) -> tuple[dict, float]:
    """One model call (or the cached reply): the checker's answer as a dict with a "verdict"."""
    prompt = PROMPT.read_text(encoding="utf-8").format(
        guide=guide, original=text.strip(), source=row.source, english="\n".join(english),
        unsupported=_UNSUPPORTED_NOTE if any(l.startswith("UNSUPPORTED") for l in english) else "")
    reply, cost = ask_cached(prompt, ROLE, ANSWER_SCHEMA, cache_dir, "faithful_row")
    try:
        answer = json.loads(reply["text"])
        if answer["verdict"] in VERDICTS:
            return {"verdict": answer["verdict"], "reading": str(answer.get("reading", "")).strip(),
                    "reason": str(answer.get("reason", "")).strip()}, cost
    except (ValueError, KeyError, TypeError):
        pass
    return {"verdict": "cannot_tell", "reading": "", "reason": "the checker's reply was not valid"}, cost


def _with_answer(row: RowResult, english: list[str], answer: dict) -> RowResult:
    """Record the checker's answer on the row."""
    verdict = answer["verdict"]
    row = replace(row, english=" ".join(english), reading="", why="")
    if verdict == "faithful":
        return replace(row, faithful=True, note="")
    if verdict == "interpreted":
        reading, why = answer["reading"] or "one of the possible readings", answer["reason"]
        return replace(row, faithful=True, reading=reading, why=why,
                       note=f"read as {reading}" + (f" ({why})" if why else ""))
    if verdict == "mismatch":
        return replace(row, faithful=False, note=answer["reason"])
    return replace(row, faithful=None, note=answer["reason"] or "could not tell if the code matches")


def check_faithfulness(engine: Engine, text: str, rows: list[RowResult], cache_dir: Path = CACHE_DIR,
                       translate_cache_dir: Path = TRANSLATE_CACHE_DIR) -> tuple[list[RowResult], float]:
    """Set english/faithful/note on rows, re-translating rows that do not match.

    Returns (rows, cost in USD); cached replies cost nothing.
    """
    rows, total, guide = list(rows), 0.0, engine.notation_guide()
    for i in range(len(rows)):
        attempts = 1  # the translation we were given
        while _needs_check(rows[i]):
            english = _english(engine, rows, i)
            if all(line.startswith("UNSUPPORTED") for line in english):  # nothing to compare: skip the call
                answer, cost = {"verdict": "cannot_tell", "reading": "",
                                "reason": "the code can't be put into words, so it couldn't be compared"}, 0.0
            else:
                answer, cost = _judge(guide, text, rows[i], english, cache_dir)
            total += cost
            if answer["verdict"] != "mismatch":
                rows[i] = _with_answer(rows[i], english, answer)
                break
            reason = answer["reason"] or "the code does not match the written row"
            if attempts >= MAX_ATTEMPTS:
                rows[i] = replace(rows[i], status="cannot", code="", faithful=False, english=" ".join(english),
                                  note=f"couldn't read this row reliably: {reason}")
                break
            attempts += 1
            feedback = f"{reason} (your code read back as: {' '.join(english)})"
            rows[i], cost = retranslate_row(engine, text, rows, i, feedback, translate_cache_dir)
            total += cost
    return rows, total
