"""Step 2b: count-guided retry. When a row's stated count disagrees with what its code makes,
ask the translator once whether the wording allows another reasonable reading that gives the
stated count (a crocheter would reread the words too).

Which rows: rows with code that state a count (not multi-size) where the code, checked as a
prefix of the pattern the way the verdict does it, fits the count under neither counting
reading of the turning chain. Those the verdict can already explain are left alone.

The guard: the new code is used only if it differs, makes the stated count by itself, and the
faithfulness checker (told the translator's explanation) calls it "interpreted" or "faithful".
Then the row is marked interpreted, so the user is told what the pattern is assumed to mean.
Anything else keeps the original code and the row still breaks. One attempt per row.
"""

import json
from dataclasses import replace
from pathlib import Path

from ..engine import Engine
from ..models.client import ROOT
from ..patterns.stated import stated_count, turning_chain_says
from .faithful import CACHE_DIR as FAITHFUL_CACHE_DIR
from .faithful import _english, _judge
from .report import RowResult
from .translate import CACHE_DIR as TRANSLATE_CACHE_DIR
from .translate import _rows_listing, ask_cached
from .verdict import PLAIN, READINGS, _counts, _Row

ROLE = "translator"
PROMPT = ROOT / "frogless" / "prompts" / "reconcile_row.md"
CACHE_DIR = ROOT / "logs" / "cache" / "reconcile_row"
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"code": {"type": "string"}, "explanation": {"type": "string"}},
    "required": ["code", "explanation"],
    "additionalProperties": False,
}


def _counts_made(engine: Engine, rows: list[RowResult], i: int, code: str,
                 clean: bool = False) -> tuple[int, dict[str, list[int]]] | None:
    """(stated count, counts row i's `code` may make per reading), or None when there is nothing to compare.

    A stitch-count error (e.g. stitches worked past the end of the row below) still gives counts:
    that is exactly when another reading is worth trying. With clean=True the code must check with
    no error at all (used for the new reading).
    """
    row = rows[i]
    if row.synthetic or row.status != "ok" or not row.code:
        return None
    stated = stated_count(row.source)
    if stated is None or stated.multi_size:
        return None
    if any(r.status in ("flagged", "cannot") and not r.synthetic for r in rows[:i]):
        return None  # a hole before this row: counts past it cannot be trusted
    prefix = [r.code for r in rows[:i] if r.code] + [code]
    check = engine.check("\n".join(prefix))
    if not check.rows or (not check.ok and (clean or check.error.kind == "invalid")):
        return None
    info = check.rows[-1]
    if info.index < 1:
        return None
    foundation = next((r.stitch_count for r in check.rows if r.index == 0), None)
    says = {turning_chain_says(r.source) for r in rows if not r.synthetic} - {None}
    said = says == {True}
    mapped = _Row(info.index, replace(row, code=code), info, stated)
    return stated.count, {rd: _counts(mapped, rd, foundation, said) for rd in READINGS}


def _fits(stated: int, counts: dict[str, list[int]], any_reading: bool) -> bool:
    chosen = counts.values() if any_reading else [counts[PLAIN]]
    return any(stated in c for c in chosen)


def _ask(guide: str, text: str, rows: list[RowResult], i: int, stated: int, made: int,
         cache_dir: Path) -> tuple[str, str, float]:
    row = rows[i]
    prompt = PROMPT.read_text(encoding="utf-8").format(
        guide=guide, original=text.strip(), rows=_rows_listing(rows), index=row.index, source=row.source,
        code=row.code, said=stated, made=made)
    reply, cost = ask_cached(prompt, ROLE, ANSWER_SCHEMA, cache_dir, "reconcile_row")
    try:
        answer = json.loads(reply["text"])
        return str(answer["code"]).strip(), str(answer["explanation"]).strip(), cost
    except (ValueError, KeyError, TypeError):
        return "", "", cost


def reconcile_counts(engine: Engine, text: str, rows: list[RowResult], cache_dir: Path = CACHE_DIR,
                     faithful_cache_dir: Path = FAITHFUL_CACHE_DIR) -> tuple[list[RowResult], float]:
    """Give rows that miss their stated count one chance at another reading of their wording.

    Returns (rows, cost in USD); cached replies cost nothing.
    """
    rows, total, guide = list(rows), 0.0, None
    for i in range(len(rows)):
        found = _counts_made(engine, rows, i, rows[i].code)
        if found is None or _fits(found[0], found[1], any_reading=True):
            continue
        stated, counts = found
        guide = guide or engine.notation_guide()
        code, explanation, cost = _ask(guide, text, rows, i, stated, counts[PLAIN][0], cache_dir)
        total += cost
        if not code or code == rows[i].code or code.startswith("# CANNOT"):
            continue
        again = _counts_made(engine, rows, i, code, clean=True)
        if again is None or not _fits(stated, again[1], any_reading=False):
            continue
        trial = replace(rows[i], code=code, origin="model")
        english = _english(engine, rows[:i] + [trial] + rows[i + 1:], i)
        context = (f'The written row states a total of {stated}, which the row read literally does not give. '
                   f'The translator read it another way: "{explanation}". The code above makes {stated}. '
                   'Judge whether this is a genuinely possible reading of the written words that keeps every '
                   'stitch and number the row names: then answer "interpreted" (put the reading in "reading" and '
                   'what is unclear in "reason"). If it changes or drops something the row names, answer "mismatch".')
        answer, cost = _judge(guide, text, trial, english, faithful_cache_dir, context)
        total += cost
        if answer["verdict"] not in ("interpreted", "faithful"):
            continue
        reading = answer["reading"] or explanation or "one of the possible readings"
        why = answer["reason"] or f"the stated {stated} only fits this reading"
        rows[i] = replace(trial, english=" ".join(english), faithful=True, reading=reading, why=why,
                          note=f"read as {reading} ({why})")
    return rows, total
