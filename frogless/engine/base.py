"""Engine-neutral result types and the interface every backend implements."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class CheckError:
    message: str
    row: int | None = None  # row/round index, when the engine tells us
    kind: str = "invalid"  # "invalid" (syntax/structure) or "count" (stitch counts)
    hint: str = ""  # optional advice from the engine


@dataclass
class RowInfo:
    index: int  # row/round number; with a magic ring, 1 = first round
    stitch_count: int  # stitches made in this row
    stitch_types: dict[str, int] = field(default_factory=dict)  # e.g. {"sc": 6}
    unworked: int = 0  # stitches of the previous row this row never works into
    overflow: int = 0  # stitches worked past the end of the previous row


@dataclass
class CheckResult:
    ok: bool
    error: CheckError | None = None
    warnings: list[str] = field(default_factory=list)
    rows: list[RowInfo] = field(default_factory=list)
    stats: dict = field(default_factory=dict)  # raw numbers, e.g. total_stitches


@dataclass
class TranslateLine:
    source: str  # the instruction text as the translator saw it
    code: str  # engine code for it ("" if not parsed)
    parsed: bool
    reason: str = ""  # why it was not parsed
    synthetic: bool = False  # added by the translator, not in the source text


@dataclass
class TranslateResult:
    lines: list[TranslateLine] = field(default_factory=list)

    @property
    def all_parsed(self) -> bool:
        return all(line.parsed for line in self.lines)

    @property
    def code(self) -> str:
        """Code for all the parsed lines, one per line."""
        return "\n".join(line.code for line in self.lines if line.parsed and line.code)


class Engine(ABC):
    @abstractmethod
    def check(self, code: str) -> CheckResult:
        """Validate engine code and report per-row stitch counts."""

    @abstractmethod
    def translate(self, text: str) -> TranslateResult:
        """Turn written pattern text into engine code, line by line."""

    @abstractmethod
    def stitches(self) -> list[str]:
        """Stitch names the translator knows."""

    @abstractmethod
    def describe(self, code: str) -> list[str]:
        """Turn engine code back into plain English, one sentence per code line."""

    @abstractmethod
    def notation_guide(self) -> str:
        """Prompt text teaching a model to write this engine's code."""
