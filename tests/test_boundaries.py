"""Keep the engine and the model provider behind their own folders."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".venv", ".git", "misc_docs", "logs", "__pycache__", "node_modules"}
ENGINE_DIR = ROOT / "frogless" / "engine" / "crochetparade"
META_FILE = ROOT / "frogless" / "models" / "providers" / "meta.py"
THIS_FILE = Path(__file__).resolve()

ENGINE_TOKENS = [
    "crochetparade",
    "parse64",
    "processtext",
    "export_to_dot",
    "review_model",
    "deterministic_translator",
]
META_TOKENS = ["api.meta.ai", "chat/completions", "choices[", "meta_sam_parser"]


def source_files():
    for path in ROOT.rglob("*"):
        if path.suffix not in (".py", ".js") or not path.is_file():
            continue
        if SKIP_DIRS & set(path.relative_to(ROOT).parts):
            continue
        yield path


def find_leaks(tokens, allowed):
    leaks = []
    for path in source_files():
        if path.resolve() == THIS_FILE or any(a in path.parents or a == path for a in allowed):
            continue
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        leaks += [f"{path.relative_to(ROOT)}: {t}" for t in tokens if t in text]
    return leaks


def test_engine_names_stay_inside_adapter_folder():
    assert find_leaks(ENGINE_TOKENS, [ENGINE_DIR]) == []


def test_meta_wire_format_stays_in_meta_provider():
    assert find_leaks(META_TOKENS, [META_FILE]) == []


def test_scanner_sees_files():
    names = {p.name for p in source_files()}
    assert {"client.py", "adapter.py", "bridge.js"} <= names
