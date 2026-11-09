"""Step 1: turn a pattern into rows of engine code.

Rules translator first, then the stated-count gate, then a language model for each row
still flagged. Without a model, flagged rows stay flagged.

Model answers vary from run to run, so a flagged row is translated `samples` times (3 by default; the translator's
"samples" in config/models.json) and code picks the answer (_referee): answers the engine rejects (or that start the
foundation row in the wrong chain) are dropped, then an answer whose row count fits the stated count wins, then the
answer most attempts agree on, and only then does the faithfulness check look at the pick (the next best if it is a
mismatch). One exception comes first: when the rules translator's literal code misses the stated count but makes it
if the turning chain counts, that literal code is kept, never a model answer that only fits by changing the stitches.
samples=1 is one call per row.
"""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from ..engine import Engine
from ..models.client import ROOT, chat, load_config
from ..patterns.stated import stated_count
from .gate import gate_translation, row_counts
from .guards import hook_problem
from .report import RowResult

ROLE = "translator"
PROMPT = ROOT / "frogless" / "prompts" / "translate_row.md"
CACHE_DIR = ROOT / "logs" / "cache" / "translate_row"
# Structured output: the API guarantees the reply parses as this.
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"code": {"type": "string"}},
    "required": ["code"],
    "additionalProperties": False,
}


def rule_rows(engine: Engine, text: str) -> list[RowResult]:
    """Rules translator plus stated-count gate; no model calls."""
    rows = []
    for i, line in enumerate(gate_translation(engine, engine.translate(text), text).lines):
        rows.append(RowResult(
            index=i,
            source=line.source,
            code=line.code if line.parsed else "",
            origin="rules" if line.parsed else "none",
            status="ok" if line.parsed else "flagged",
            synthetic=line.synthetic,
            note="" if line.parsed else line.reason,
            literal=line.literal,
        ))
    return rows


def _rows_listing(rows: list[RowResult]) -> str:
    """Every row with its current code; '?' where there is none yet."""
    out = []
    for r in rows:
        if r.status == "ok":
            code = r.code if r.code else "(no stitches)"
        elif r.status == "cannot":
            code = "? (could not be translated)"
        else:
            code = "?"
        tag = "  [added by the translator]" if r.synthetic else ""
        out.append(f"[{r.index}] {r.source}\n    => {code}{tag}")
    return "\n".join(out)


def _row_prompt(guide: str, text: str, rows: list[RowResult], row: RowResult, feedback: str = "",
                attempt: tuple[int, int] | None = None) -> str:
    """The translate prompt for one row. `feedback` (why an earlier attempt was wrong) goes last.
    `attempt` (k, n) adds the line "Attempt k of n" at the very end: it only gives each independent attempt
    its own cache key, the static start of the prompt stays the same."""
    tail = ""
    if feedback:
        tail = ("\nYour previous attempt for this row was wrong, because: " + feedback.strip()
                + "\nTranslate it again so that the code does what the row says, with no such problem."
                " Still translate literally and never correct the pattern.\n")
    if attempt:
        tail += f"\nAttempt {attempt[0]} of {attempt[1]}\n"
    return PROMPT.read_text(encoding="utf-8").format(
        guide=guide, original=text.strip(), rows=_rows_listing(rows), index=row.index, source=row.source,
        feedback=tail)


def ask_cached(prompt: str, role: str, schema: dict, cache_dir: Path, name: str) -> tuple[dict, float]:
    """One model call, or the cached reply. Returns (reply, cost); a cached reply costs 0.

    Everything before the first "<pattern>" tag should be the same for every call of this
    `name`: the API reuses that start of the prompt (prompt caching).
    """
    role_cfg = load_config()["roles"][role]
    effort = role_cfg.get("reasoning_effort") or "default"
    key = f"{role_cfg['model']}\neffort={effort}\nschema={json.dumps(schema, sort_keys=True)}\n{prompt}"
    path = cache_dir / (hashlib.sha256(key.encode()).hexdigest()[:24] + ".json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8")), 0.0
    # The static start of the prompt is identical for every row, which lets the API reuse it
    # (prompt caching). prompt_cache_key groups the calls so they are routed together.
    static = prompt.split("<pattern>")[0]
    messages = [{"role": "user", "content": prompt}]
    cache_key = name + "-" + hashlib.sha256(static.encode()).hexdigest()[:16]
    result = chat(role, messages, json_schema=schema, prompt_cache_key=cache_key)
    cost = result.get("cost_usd") or 0.0
    # A hard row can use the whole output budget reasoning and reply with nothing:
    # try once more with the role's larger budget.
    retry_tokens = role_cfg.get("max_tokens_retry")
    if not result["text"].strip() and retry_tokens and result["usage"].get("output_tokens", 0) >= role_cfg.get("max_tokens", 0):
        result = chat(role, messages, json_schema=schema, prompt_cache_key=cache_key, max_tokens=retry_tokens)
        cost += result.get("cost_usd") or 0.0
    reply = {"text": result["text"], "usage": result["usage"], "cost_usd": cost}
    # An empty reply is kept too (the model ran out of tokens): asking again costs minutes and money.
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(reply, indent=1), encoding="utf-8")
    return reply, cost


def _ask(prompt: str, cache_dir: Path) -> tuple[dict, float]:
    return ask_cached(prompt, ROLE, ANSWER_SCHEMA, cache_dir, "translate_row")


def _apply(row: RowResult, reply: dict) -> RowResult:
    """Fill a flagged row from the model's reply."""
    done = replace(row, origin="model")
    if not reply["text"].strip():
        used = reply["usage"].get("output_tokens", 0)
        return replace(done, status="cannot", code="",
                       note=f"no answer: the model used all {used} output tokens before replying")
    try:
        code = str(json.loads(reply["text"])["code"]).strip()
    except (ValueError, KeyError, TypeError):
        return replace(done, status="cannot", code="", note="the model's reply was not valid")
    if code.startswith("# CANNOT"):
        reason = code.removeprefix("# CANNOT").lstrip(":").strip()
        return replace(done, status="cannot", code="", note=reason or "the model could not translate this row")
    return replace(done, status="ok", code=code, note="")


PICK_NOTE = "picked attempt"  # starts the note of a row chosen among several attempts


def _samples(samples: int | None) -> int:
    if samples is None:
        samples = load_config()["roles"][ROLE].get("samples", 3)
    return max(1, int(samples))


def _norm(code: str) -> str:
    return "".join(code.split()).lower()


def _evaluate(engine: Engine, rows: list[RowResult], i: int, code: str) -> tuple[bool, bool]:
    """(accepted by the engine, row count fits the stated count) for row i written as `code`, after the rows before it.
    Only invalid code is a rejection; a stated count the code misses is just not a fit."""
    check = engine.check("\n".join([r.code for r in rows[:i] if r.code] + [code]))
    if check.error is not None and check.error.kind == "invalid":
        return False, False
    stated = stated_count(rows[i].source)
    if not code or stated is None or stated.multi_size or not check.ok or not check.rows:
        return True, False
    return True, stated.count in row_counts(check.rows[-1], stated.stitch)


def _only_if_turning_chain_counts(engine: Engine, rows: list[RowResult], i: int, code: str) -> bool:
    """True when row i written as `code` misses its stated count counted plainly but makes it with the turning chain
    counted as a stitch (verdict.py's other reading): the code is a fair literal reading of a pattern that counts that way."""
    from .reconcile import PLAIN, _counts_made  # reconcile.py imports this module

    found = _counts_made(engine, rows[:i] + [replace(rows[i], status="ok", code=code)] + rows[i + 1:], i, code)
    if found is None:
        return False
    stated, counts = found
    return stated not in counts[PLAIN] and any(stated in c for c in counts.values())


def _referee(engine: Engine, text: str, rows: list[RowResult], i: int, candidates: list[RowResult],
             judge_cache_dir: Path | None) -> tuple[RowResult, float]:
    """Pick the row among the independent attempts at row i. Code first, the language model last:
    drop the attempts the engine rejects, and those that start the foundation row in the wrong chain; prefer one whose
    count fits the stated count; prefer the one most attempts agree on; only then ask the faithfulness check about the
    pick, and about the next best if it is a mismatch. The pick's note says which attempt won and why.
    The exception: when the rules translator's literal code (rows[i].literal) misses the stated count only because
    the turning chain is not counted, it is the pick, whatever the model's attempts say: a count that fits by
    changing the stitches is a silent fix. Returns (row, cost in USD)."""
    from . import faithful  # faithful.py imports this module

    n, cost = len(candidates), 0.0
    ok = [(k, c) for k, c in enumerate(candidates, 1) if c.status == "ok"]
    if not ok:
        return candidates[0], cost
    judged = {k: _evaluate(engine, rows, i, c.code) for k, c in ok}
    accepted = [(k, c) for k, c in ok if judged[k][0]]
    dropped = len(ok) - len(accepted)
    before, lines = "\n".join(r.code for r in rows[:i] if r.code), [r.source for r in rows if not r.synthetic]
    valid = [(k, c) for k, c in accepted if not hook_problem(engine, before, c.code, rows[i].source, lines)]
    wrong_start = len(accepted) - len(valid) if valid else 0
    pool = valid or accepted or ok  # if the engine rejects every attempt, the retry loop deals with them
    literal = rows[i].literal
    keep_literal = bool(literal) and _evaluate(engine, rows, i, literal)[0] and _only_if_turning_chain_counts(
        engine, rows, i, literal)
    if keep_literal:  # the literal reading joins the attempts as number 0
        judged[0] = (True, False)
        pool = [(0, replace(rows[i], status="ok", code=literal, origin="rules", note=""))] + pool
    groups: dict[str, list[tuple[int, RowResult]]] = {}
    for k, c in pool:
        groups.setdefault(_norm(c.code), []).append((k, c))
    wanted = _norm(literal) if keep_literal else None  # the literal group comes first, then the count fit, then agreement
    ranked = sorted(groups.values(), key=lambda g: (_norm(g[0][1].code) != wanted, not judged[g[0][0]][1], -len(g), g[0][0]))

    def pick(group, tail: str = "") -> RowResult:
        k, c = group[0]
        if keep_literal and _norm(c.code) == wanted:
            return replace(c, note="kept the literal reading: its count fits only if the turning chain counts")
        why = []
        if judged[k][1]:
            why.append("its count fits the stated count")
        if len(group) > 1:
            why.append(f"{len(group)} of {n} attempts agree")
        if dropped:
            why.append(f"{dropped} rejected by the engine")
        if wrong_start:
            why.append(f"{wrong_start} started in the wrong chain from the hook")
        if tail:
            why.append(tail)
        return replace(c, note=f"{PICK_NOTE} {k} of {n}" + (": " + ", ".join(why) if why else ""))

    if len(ranked) == 1 or keep_literal:  # the literal needs no judge: check_faithfulness reads it back later
        return pick(ranked[0]), cost
    guide = engine.notation_guide()
    for tried, group in enumerate(ranked):
        k, c = group[0]
        later = "" if tried == 0 else "an earlier pick did not match the row"
        if not c.code:  # a prose row: nothing to compare
            return pick(group, later), cost
        english = faithful._english(engine, rows[:i] + [c], i)
        if all(line.startswith("UNSUPPORTED") for line in english):  # nothing to compare: take it
            return pick(group, later), cost
        answer, spent = faithful._judge(guide, text, c, english, judge_cache_dir or faithful.CACHE_DIR)
        cost += spent
        if answer["verdict"] != "mismatch":
            return pick(group, later), cost
    return pick(ranked[0], "the check found a mismatch in every attempt"), cost


def translate_flagged(engine: Engine, text: str, rows: list[RowResult],
                      cache_dir: Path = CACHE_DIR, samples: int | None = None,
                      judge_cache_dir: Path | None = None) -> tuple[list[RowResult], float]:
    """Fill flagged rows using the model, in order.

    Each row is translated `samples` times independently (None: the translator's "samples" setting, 3 if unset)
    and the referee picks (_referee); samples=1 is one call per row. Later rows see earlier model answers as
    context. Synthetic and already-translated rows are never sent. Returns (rows, cost in USD); cached replies
    cost nothing.
    """
    rows, total = list(rows), 0.0
    todo = [i for i, r in enumerate(rows) if r.status == "flagged" and not r.synthetic]
    if not todo:
        return rows, total
    guide, samples = engine.notation_guide(), _samples(samples)
    for i in todo:
        if samples == 1:
            reply, cost = _ask(_row_prompt(guide, text, rows, rows[i]), cache_dir)
            total += cost
            rows[i] = _apply(rows[i], reply)
            continue
        # attempt 1 is the plain prompt (the same cache entry as a single attempt); the others carry a nonce line
        prompts = [_row_prompt(guide, text, rows, rows[i], attempt=(k, samples) if k > 1 else None)
                   for k in range(1, samples + 1)]
        with ThreadPoolExecutor(samples) as pool:
            replies = list(pool.map(lambda p: _ask(p, cache_dir), prompts))
        total += sum(cost for _, cost in replies)
        rows[i], spent = _referee(engine, text, rows, i, [_apply(rows[i], reply) for reply, _ in replies],
                                  judge_cache_dir)
        total += spent
    return rows, total


def retranslate_row(engine: Engine, text: str, rows: list[RowResult], i: int, feedback: str,
                    cache_dir: Path = CACHE_DIR) -> tuple[RowResult, float]:
    """Translate row i again with the model, telling it why the last attempt was wrong.

    Returns (the new row, cost in USD). The other rows are shown as context, unchanged.
    """
    row = replace(rows[i], status="flagged", code="", note="")
    context = list(rows)
    context[i] = row
    reply, cost = _ask(_row_prompt(engine.notation_guide(), text, context, row, feedback), cache_dir)
    return _apply(row, reply), cost
