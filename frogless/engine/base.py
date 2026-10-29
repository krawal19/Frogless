"""Engine-neutral result types and the interface every backend implements."""

import re
from abc import ABC, abstractmethod
from collections import Counter
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


@dataclass(frozen=True)
class RowItem:
    """One stitch or chain the way a row's code writes it: `count` of the same kind in a row ("7dc"),
    inside `times` repeats of the groups around it."""

    kind: str  # e.g. "dc", "sc2inc", "ch"
    count: int = 1
    times: int = 1


@dataclass
class ReadingDiff:
    """How another reading of a row (the candidate) differs from its literal code, structurally."""

    dropped: bool  # the candidate is the literal with items removed (a strict sub-multiset of the items)
    same_shape: bool  # same items in the same order and groups; only the numbers beside them differ
    number_changes: list[tuple[str, int, int]]  # (kind, literal count, candidate count) for each changed number
    consumes: tuple[int, int] | None  # stitches of the earlier rows each works into; None if the engine cannot say


_FAMILY = re.compile(r"^(?:fp|bp)?(ss|sc|hdc|dc|dtr|ttr|trtr|tr|ch|sk)")


def stitch_family(kind: str) -> str:
    """The stitch a kind is a form of: "dc2inc" and "dcfl" are "dc"; "" for an unknown kind."""
    m = _FAMILY.match(kind)
    return m.group(1) if m else ""


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

    # ---- comparing readings of one row ----
    def row_items(self, code: str) -> list[RowItem] | None:
        """The stitches and chains one row's code writes, in order, or None when the engine cannot list them."""
        return None

    def consumes(self, before: str, code: str) -> int | None:
        """How many stitches of the earlier rows the last row of `before` + `code` works into (the stitch graph),
        or None when the code does not check."""
        check = self.check("\n".join(c for c in (before, code) if c.strip()))
        if not check.rows or (check.error is not None and check.error.kind == "invalid"):
            return None
        row = check.rows[-1]
        if not row.stitches:
            return None
        return len({target for st in row.stitches for target in st.into})

    def compare_readings(self, literal: str, candidate: str, before: str = "") -> ReadingDiff | None:
        """How `candidate` differs structurally from `literal` (both the code of the same row, after the code
        of the rows `before` it). None when either cannot be listed."""
        lit, cand = self.row_items(literal), self.row_items(candidate)
        if not lit or not cand:
            return None
        lit_kinds, cand_kinds = Counter(i.kind for i in lit), Counter(i.kind for i in cand)
        dropped = (all(lit_kinds[k] >= n for k, n in cand_kinds.items())
                   and sum(cand_kinds.values()) < sum(lit_kinds.values()))
        same_shape = [(i.kind, i.times) for i in lit] == [(i.kind, i.times) for i in cand]
        changes = [(a.kind, a.count, b.count) for a, b in zip(lit, cand) if same_shape and a.count != b.count]
        a, b = self.consumes(before, literal), self.consumes(before, candidate)
        return ReadingDiff(dropped, same_shape, changes, (a, b) if a is not None and b is not None else None)

    def reading_drops_items(self, literal: str, candidate: str, before: str = "", named: tuple[str, ...] = ()) -> bool:
        """True when `candidate` is `literal` with stitches or chains removed: a strict sub-multiset of its items,
        or a stitch family the row's text names (`named`, e.g. "sc", "ch") that is gone from it entirely.
        A different number on an item ("7dc" read as "3dc") is not a removal. With no `literal`, only `named` counts."""
        cand = self.row_items(candidate)
        if cand is None:
            return False
        if literal.strip() and cand:
            diff = self.compare_readings(literal, candidate, before)
            if diff is not None and diff.dropped:
                return True
        lit = self.row_items(literal) if literal.strip() else None
        worked = {stitch_family(i.kind) for i in lit} if lit else None
        have = {stitch_family(i.kind) for i in cand}
        return any(n not in have and (worked is None or n in worked) for n in named)

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
    def render(self, code: str, out_dir, name: str = "render") -> dict:
        """Draw the pattern to images in out_dir, files named after `name`.

        Returns {"model_3d": path|None, "chart_2d": path|None, "error": str|None}, where chart_2d is the
        standard crochet symbol chart; "connectivity_2d" and "overlay_2d" may hold the other chart views;
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
