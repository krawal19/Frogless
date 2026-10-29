"""Step 2: check each row's code says what the pattern says.

Code -> English via the engine's describe(), then a model compares it with the original
row (one call per row). On a mismatch the row is translated again, told what was wrong; after
three translation attempts in all, the row is marked unreadable rather than guessed at.
A row that writes a phrase twice in a row gets its code put right first if the model merged the two (restore_repeats).
An "interpreted" verdict is refused (as a mismatch) for code that differs from the first translation and
deletes from it or moves its stitches (guards.py).

Which rows: every row that has code (the model's and the rules translator's, also rules rows that
state a count; only the magic ring the translator adds itself is skipped). A mismatching rule row goes
to the model translator once.

Before the checker is asked, code the model wrote is run through the engine (this row's code after
the rows before it). If the engine rejects it as invalid (an unknown stitch name, say) the row is
translated again, told the engine's message. That takes one of the three attempts too.
"""

import json
from collections import Counter
from dataclasses import replace
from pathlib import Path

from ..engine import Engine
from ..models.client import ROOT
from ..patterns.placement import repeated_phrases
from .guards import reading_problem
from .report import RowResult
from .translate import CACHE_DIR as TRANSLATE_CACHE_DIR
from .translate import PICK_NOTE, ask_cached, retranslate_row

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
    return not row.synthetic and row.status == "ok" and bool(row.code)


def _has_more_items(engine: Engine, new: str, old: str) -> bool:
    """True when `new` writes every stitch and chain of `old` and more besides (engines that cannot list say no)."""
    if not hasattr(engine, "row_items"):
        return False
    a, b = engine.row_items(new), engine.row_items(old)
    if not a or not b:
        return False
    have, was = Counter(i.kind for i in a), Counter(i.kind for i in b)
    return all(have[k] >= n for k, n in was.items()) and sum(have.values()) > sum(was.values())


def restore_repeats(engine: Engine, text: str, rows: list[RowResult], i: int,
                    cache_dir: Path = TRANSLATE_CACHE_DIR) -> tuple[RowResult, float]:
    """Row i with a repeated instruction put back when the model's code merged it (guards.py needs a literal code that
    still has everything the row writes). A row that writes a phrase twice in a row ("Ch5, 2dc in same space. Ch5, 2dc
    in same space") is translated once more, told to do it twice; the new code replaces the old only if it writes
    everything the old one did and more, and the engine accepts it. Returns (row, cost in USD)."""
    row = rows[i]
    if row.origin != "model" or not row.code or row.synthetic:
        return row, 0.0
    phrases = repeated_phrases(row.source)
    if not phrases:
        return row, 0.0
    said = " and ".join(f'"{p}"' for p in phrases)
    feedback = (f"the row writes {said} twice in a row, and each copy is an instruction to work it: the code must do it "
                "twice, once for each time it is written, not once. Never merge or skip a repeated instruction, "
                "even if the second copy looks like a typo")
    again, cost = retranslate_row(engine, text, rows, i, feedback, cache_dir)
    if again.status == "ok" and again.code != row.code and _has_more_items(engine, again.code, row.code)             and not _rejection(engine, rows[:i] + [again], i):
        return replace(row, code=again.code), cost
    return row, cost


def _rejection(engine: Engine, rows: list[RowResult], i: int) -> str:
    """Why the engine rejects row i's code (with the rows before it), or "" if it accepts it.
    Only invalid code counts; a wrong stitch count is left to the verdict."""
    if rows[i].origin != "model":
        return ""
    check = engine.check("\n".join(r.code for r in rows[:i + 1] if r.code))
    if check.error is not None and check.error.kind == "invalid":
        return check.error.message
    return ""


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


def _judge(guide: str, text: str, row: RowResult, english: list[str], cache_dir: Path,
           context: str = "") -> tuple[dict, float]:
    """One model call (or the cached reply): the checker's answer as a dict with a "verdict".
    `context` is extra text for the checker, placed just before it gives its verdict."""
    prompt = PROMPT.read_text(encoding="utf-8").format(
        guide=guide, original=text.strip(), source=row.source, english="\n".join(english),
        unsupported=_UNSUPPORTED_NOTE if any(l.startswith("UNSUPPORTED") for l in english) else "")
    if context:
        head, _, tail = prompt.rpartition("Give your verdict now.")
        prompt = f"{head}{context.strip()}\n\nGive your verdict now.{tail}"
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
    picked = row.note if row.note.startswith(PICK_NOTE) else ""  # which of several translations was chosen, and why
    row = replace(row, english=" ".join(english), reading="", why="")
    if verdict == "faithful":
        return replace(row, faithful=True, note=picked)
    if verdict == "interpreted":
        reading, why = answer["reading"] or "one of the possible readings", answer["reason"]
        return replace(row, faithful=True, reading=reading, why=why,
                       note=f"read as {reading}" + (f" ({why})" if why else "") + (f"; {picked}" if picked else ""))
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
        if _needs_check(rows[i]):
            rows[i], cost = restore_repeats(engine, text, rows, i, translate_cache_dir)
            total += cost
        first = rows[i].code  # ... the literal one, which a later "interpreted" code must not delete from
        while _needs_check(rows[i]):
            rejected = _rejection(engine, rows, i)
            if rejected:
                if attempts >= MAX_ATTEMPTS:
                    rows[i] = replace(rows[i], status="cannot", code="",
                                      note=f"couldn't read this row reliably: the code was rejected ({rejected})")
                    break
                attempts += 1
                rows[i], cost = retranslate_row(
                    engine, text, rows, i, f"the checker rejected your code `{rows[i].code}`: {rejected}",
                    translate_cache_dir)
                total += cost
                continue
            english = _english(engine, rows, i)
            if all(line.startswith("UNSUPPORTED") for line in english):  # nothing to compare: skip the call
                answer, cost = {"verdict": "cannot_tell", "reading": "",
                                "reason": "the code can't be put into words, so it couldn't be compared"}, 0.0
            else:
                answer, cost = _judge(guide, text, rows[i], english, cache_dir)
            total += cost
            if answer["verdict"] == "interpreted" and rows[i].code != first:  # hard rule: no deleting, no moving
                problem = reading_problem(engine, "\n".join(r.code for r in rows[:i] if r.code), first, rows[i].code,
                                          rows[i].source)
                if problem:
                    answer = {"verdict": "mismatch", "reading": "", "reason": problem}
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
