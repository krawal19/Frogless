"""Step 1: turn a pattern into rows of engine code.

Rules translator first, then the stated-count gate, then a language model for each row
still flagged, one call per row. Without a model, flagged rows stay flagged.
"""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

from ..engine import Engine
from ..models.client import ROOT, chat, load_config
from .gate import gate_translation
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


def _row_prompt(guide: str, text: str, rows: list[RowResult], row: RowResult, feedback: str = "") -> str:
    """The translate prompt for one row. `feedback` (why an earlier attempt was wrong) goes last."""
    tail = ""
    if feedback:
        tail = ("\nYour previous attempt for this row was wrong, because: " + feedback.strip()
                + "\nTranslate it again so that the code does what the row says, with no such problem."
                " Still translate literally and never correct the pattern.\n")
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
    if reply["text"].strip():  # an empty reply is not worth keeping: retry it next run
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


def translate_flagged(engine: Engine, text: str, rows: list[RowResult],
                      cache_dir: Path = CACHE_DIR) -> tuple[list[RowResult], float]:
    """Fill flagged rows using the model, one call per row, in order.

    Later rows see earlier model answers as context. Synthetic and already-translated rows
    are never sent. Returns (rows, cost in USD); cached replies cost nothing.
    """
    rows, total = list(rows), 0.0
    todo = [i for i, r in enumerate(rows) if r.status == "flagged" and not r.synthetic]
    if not todo:
        return rows, total
    guide = engine.notation_guide()
    for i in todo:
        reply, cost = _ask(_row_prompt(guide, text, rows, rows[i]), cache_dir)
        total += cost
        rows[i] = _apply(rows[i], reply)
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
