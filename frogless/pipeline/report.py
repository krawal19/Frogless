"""What check_pattern() returns. Engine-neutral: no engine syntax beyond the code strings."""

from dataclasses import dataclass, field

from ..engine import CheckResult


@dataclass
class RowResult:
    index: int  # position among the translated rows (0-based)
    source: str  # the row's text as the translator saw it
    code: str = ""  # final engine code for this row ("" if none)
    origin: str = "rules"  # "rules" (rules translator), "model" (language model), "none"
    status: str = "ok"  # "ok", "flagged" (no code yet), "cannot" (model said it can't)
    synthetic: bool = False  # added by the translator, not written in the pattern
    note: str = ""  # why it was flagged, or the model's CANNOT reason
    english: str = ""  # the code turned back into English (faithfulness check)
    faithful: bool | None = None  # None = not checked


@dataclass
class Verdict:
    kind: str  # "works", "works_unverified", "breaks", "ambiguous", "unreadable"
    message: str
    row: int | None = None  # the pattern's row/round number where it breaks
    readings: list[str] = field(default_factory=list)  # for "ambiguous": the readings that fit
    reading: str = ""  # counting convention the verdict was reached under ("" if it did not matter)
    rows: list[int] = field(default_factory=list)  # for "works_unverified": rows the model wrote and nothing confirmed


@dataclass
class PatternReport:
    text: str
    rows: list[RowResult]
    check: CheckResult | None = None  # engine result on the assembled code
    verdict: Verdict | None = None
    stated: dict[int, int] = field(default_factory=dict)  # row number -> count the pattern states
    computed: dict[int, int] = field(default_factory=dict)  # row number -> count the engine makes
    cost_usd: float = 0.0  # model spend for this check
    notes: list[str] = field(default_factory=list)  # anything else worth telling the user

    @property
    def code(self) -> str:
        return "\n".join(r.code for r in self.rows if r.code)
