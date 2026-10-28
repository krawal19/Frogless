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
class StitchInfo:
    """One stitch of a row, as a node of the stitch graph."""

    position: int  # 0-based place in its row, in working order
    kind: str  # e.g. "sc", "dc2inc", "ch", "ss"
    into: list[tuple[int, int]] = field(default_factory=list)  # (row index, position) it is worked into
    label: str = ""  # name the pattern gave this stitch or space, if any


@dataclass
class RowInfo:
    index: int  # row/round number; with a magic ring, 1 = first round
    stitch_count: int  # stitches made in this row
    stitch_types: dict[str, int] = field(default_factory=dict)  # e.g. {"sc": 6}
    unworked: int = 0  # stitches of the previous row this row never works into
    overflow: int = 0  # stitches worked past the end of the previous row
    stitches: list[StitchInfo] = field(default_factory=list)  # the row's stitches, when the engine provides them


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

    def resolve(self, code: str) -> str:
        """Engine code with "into the next chain space" (@sp) written out as named spaces.

        Raises ValueError when an @sp has no space to reach. Code without @sp comes back unchanged.
        """
        return code

    def is_marker(self, source: str) -> bool:
        """True for a translated line that is only a marker of the translator ("start the next piece"):
        no instruction, no code to check, and no row number of its own."""
        return False

    @abstractmethod
    def stitches(self) -> list[str]:
        """Stitch names the translator knows."""

    @abstractmethod
    def describe(self, code: str) -> list[str]:
        """Turn engine code back into plain English, one sentence per code line."""

    @abstractmethod
    def encode(self, spec) -> str:
        """Turn an engine-neutral pattern spec (frogless.testset.spec.Spec) into engine code."""

    @abstractmethod
    def render(self, code: str, out_dir) -> dict:
        """Draw the pattern to images in out_dir.

        Returns {"model_3d": path|None, "chart_2d": path|None, "error": str|None};
        backends may add more keys (for example extra camera angles).
        """

    def render_many(self, items, out_dir) -> list[dict]:
        """Render several (name, code[, dim[, chart]]) items; backends can override to share a browser."""
        return [self.render(item[1], out_dir) for item in items]

    @abstractmethod
    def visual_samples(self) -> list[dict]:
        """Sample patterns for eyeballing renders: [{name, code, expected_shape}]."""

    @abstractmethod
    def notation_guide(self) -> str:
        """Prompt text teaching a model to write this engine's code."""
