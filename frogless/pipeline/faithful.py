"""Step 2: check each row's code says what the pattern says (task 8).

Code -> English via the engine's describe(), then a model compares it with the original
row; on a mismatch the row is re-translated (max 3 tries), else marked unreadable.
"""

from ..engine import Engine
from .report import RowResult


def check_faithfulness(engine: Engine, text: str, rows: list[RowResult]) -> tuple[list[RowResult], float]:
    """Set english/faithful on rows. Returns (rows, cost in USD). TODO task 8."""
    return rows, 0.0
