"""Export the lines the rules translator could not read, for a model to translate.

Run from the repo root:
    python -m scripts.flagged_export [--patterns FOLDER] [--out DIR]

Writes two files to DIR (default logs/flagged):
  input.json  what a model sees: each pattern's original text and its translated rows,
              with flagged rows marked (code is null there)
  key.json    expected answers for synthetic cases; never shown to the model
Synthetic cases come from the test bench; only those the English route cannot read
are exported. Lines whose translation misses their stated stitch count are flagged too
(see frogless/pipeline/gate.py). No model calls.
"""

import argparse
import json
from pathlib import Path

from frogless.engine import get_engine
from frogless.pipeline.gate import gate_translation
from frogless.testset.generators import ROOT, base_cases, load_config
from frogless.testset.inject import injected_cases


def rows_of(engine, text):
    rows = []
    for i, line in enumerate(gate_translation(engine, engine.translate(text), text).lines):
        rows.append({
            "row": i,
            "text": line.source,
            "flagged": not line.parsed,
            "code": line.code if line.parsed else None,
        })
    return rows


def export(engine, cfg, patterns):
    items, key = [], {}
    bases = base_cases(cfg)
    for case in bases + injected_cases(cfg, bases):
        rows = rows_of(engine, case["english"])
        if not any(r["flagged"] for r in rows):
            continue
        items.append({"id": case["id"], "original": case["english"], "rows": rows})
        key[case["id"]] = case["expected"]
    if patterns:
        for path in sorted(patterns.glob("*.txt")):
            text = path.read_text(encoding="utf-8")
            items.append({"id": f"{patterns.name}:{path.stem}", "original": text,
                          "rows": rows_of(engine, text)})
    return items, key


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--patterns", type=Path, help="also export a folder of real pattern .txt files")
    parser.add_argument("--out", type=Path, default=ROOT / "logs" / "flagged")
    args = parser.parse_args()

    items, key = export(get_engine(), load_config(), args.patterns)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "input.json").write_text(json.dumps(items, indent=1), encoding="utf-8")
    (args.out / "key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    flagged = sum(r["flagged"] for it in items for r in it["rows"])
    print(f"{len(items)} patterns, {flagged} flagged rows -> {args.out}")


if __name__ == "__main__":
    main()
