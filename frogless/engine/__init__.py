"""Pattern-checking engine. The only public entry point is get_engine()."""

import importlib
import json
from pathlib import Path

from .base import (
    CheckError,
    CheckResult,
    Engine,
    ReadingDiff,
    RowInfo,
    RowItem,
    StitchInfo,
    TranslateLine,
    TranslateResult,
    stitch_family,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "engine.json"

__all__ = [
    "CheckError",
    "CheckResult",
    "Engine",
    "ReadingDiff",
    "RowInfo",
    "RowItem",
    "StitchInfo",
    "TranslateLine",
    "TranslateResult",
    "get_engine",
    "stitch_family",
]


def get_engine() -> Engine:
    """Build the backend named in config/engine.json (folder name = backend name)."""
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    backend = cfg["backend"]
    try:
        module = importlib.import_module(f".{backend}.adapter", __package__)
    except ModuleNotFoundError as e:
        raise KeyError(f"unknown engine backend {backend!r}") from e
    return module.create_engine(cfg[backend])
