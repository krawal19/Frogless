"""Ask a model to translate the flagged rows exported by scripts/flagged_export.py.

Run from the repo root:
    python -m scripts.flagged_translate [--dir DIR] [--role ROLE] [--workers N]

One model call per pattern, using the prompt in frogless/prompts/translate_flagged.md
and the engine's notation guide. Answers are cached in DIR/cache/ by a hash of the
model and prompt, so re-running never pays twice for the same call. Writes
DIR/answers_<model>.json in the format scripts/flagged_score.py reads.
"""

import argparse
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from frogless.engine import get_engine
from frogless.models.client import chat, load_config
from frogless.testset.generators import ROOT

PROMPT = ROOT / "frogless" / "prompts" / "translate_flagged.md"
MAX_TOKENS = 16000  # Spark's hidden reasoning counts toward this
# Structured output: {"<row>": "<code>"}; the API guarantees the reply parses as this.
ANSWER_SCHEMA = {"type": "object", "additionalProperties": {"type": "string"}}


def parse_answer(text):
    """The model should reply with one JSON object; take the outermost {...} if it adds anything."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        return json.loads(match.group(0)) if match else None
    except json.JSONDecodeError:
        return None


def translate(item, guide, role, model, effort, cache):
    pattern = json.dumps({"original": item["original"], "rows": item["rows"]}, indent=1)
    prompt = PROMPT.read_text(encoding="utf-8").format(guide=guide, pattern=pattern)
    key = f"{model}\neffort={effort}\nschema={json.dumps(ANSWER_SCHEMA)}\n{prompt}"
    path = cache / (hashlib.sha256(key.encode()).hexdigest()[:24] + ".json")
    if path.exists():
        reply = json.loads(path.read_text(encoding="utf-8"))
    else:
        result = chat(role, [{"role": "user", "content": prompt}], max_tokens=MAX_TOKENS,
                      json_schema=ANSWER_SCHEMA, reasoning_effort=None if effort == "default" else effort)
        reply = {"text": result["text"], "usage": result["usage"], "cost_usd": result["cost_usd"]}
        if reply["text"].strip():  # an empty reply is not worth keeping: retry it next run
            path.write_text(json.dumps(reply, indent=1), encoding="utf-8")
    flagged = [str(r["row"]) for r in item["rows"] if r["flagged"]]
    if not reply["text"].strip():
        why = f"no answer, the model used all {reply['usage']['output_tokens']} output tokens reasoning"
        return item["id"], {row: f"# CANNOT: {why}" for row in flagged}, reply.get("cost_usd") or 0
    answers = parse_answer(reply["text"])
    if answers is None:
        answers = {row: "# CANNOT: reply was not valid JSON" for row in flagged}
    return item["id"], answers, reply.get("cost_usd") or 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, default=ROOT / "logs" / "flagged")
    parser.add_argument("--role", default="translator")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--effort", help="reasoning effort: default (model chooses), minimal, low, medium, "
                                         "high, xhigh, max; omitted = the role's setting in config/models.json")
    parser.add_argument("--ids", nargs="+", help="only these pattern ids")
    args = parser.parse_args()

    role_cfg = load_config()["roles"][args.role]
    model = role_cfg["model"]
    effort = args.effort or role_cfg.get("reasoning_effort") or "default"
    items = json.loads((args.dir / "input.json").read_text(encoding="utf-8"))
    if args.ids:
        items = [it for it in items if it["id"] in args.ids]
    guide = get_engine().notation_guide()
    cache = args.dir / "cache"
    cache.mkdir(parents=True, exist_ok=True)

    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(lambda it: translate(it, guide, args.role, model, effort, cache), items))

    out = args.dir / f"answers_{model}_{effort}.json"
    out.write_text(json.dumps({pid: ans for pid, ans, _ in results}, indent=1), encoding="utf-8")
    print(f"{len(results)} patterns translated by {model} (effort {effort}), cost ${sum(c for *_, c in results):.3f} "
          f"(cached calls count as $0) -> {out}")


if __name__ == "__main__":
    main()
