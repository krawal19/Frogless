"""Make broken copies of working cases, each with an exact expected break row.

The English is re-rendered from the broken spec but keeps the stated counts of the
original, so a wrong count shows as "(18)" next to a round that really makes 19.
"""

import copy
import random

from .generators import make_case
from .spec import Item, Repeat, consumed

TYPES = ["extra_stitch", "missing_stitch", "extra_inc", "missing_round", "impossible_increase"]


def _stitch(items):
    """Main stitch of a row (first plain item found)."""
    for x in items:
        s = _stitch(x.items) if isinstance(x, Repeat) else x.stitch
        if s:
            return s


# ---- row mutations: each returns a new item list, or None if it does not apply ----
def extra_stitch(items):
    return items + [Item("st", _stitch(items), 1)]


def missing_stitch(items):
    last = items[-1]
    if isinstance(last, Repeat):  # drop one stitch of the last repeat's span
        rest = [Repeat(last.items, last.times - 1)] if last.times > 1 else []
        c = consumed(last.items) - 1
        return items[:-1] + rest + ([Item("st", _stitch(items), c)] if c else [])
    if last.n > 1:
        return items[:-1] + [Item(last.kind, last.stitch, last.n - 1)]
    return items[:-1] or None


def extra_inc(items):
    """Same stitches worked into, but one stitch more made (an inc where a sc should be)."""
    for i, x in enumerate(items):
        if isinstance(x, Repeat):
            inner = extra_inc(x.items)
            if inner:
                rest = [Repeat(x.items, x.times - 1)] if x.times > 1 else []
                return items[:i] + rest + inner + items[i + 1 :]
        elif x.kind == "st":
            more = [Item("st", x.stitch, x.n - 1)] if x.n > 1 else []
            return items[:i] + more + [Item("inc", x.stitch)] + items[i + 1 :]
    return None


def impossible_increase(items):
    """Two more increases than there are stitches to work them into."""
    for i, x in enumerate(items):
        if isinstance(x, Repeat) and any(isinstance(y, Item) and y.kind == "inc" for y in x.items):
            return items[:i] + [Repeat(x.items, x.times + 2)] + items[i + 1 :]
        if isinstance(x, Item) and x.kind == "inc":
            return items[:i] + [Item("inc", x.stitch, x.n + 2)] + items[i + 1 :]
    return None


MUTATIONS = {
    "extra_stitch": extra_stitch,
    "missing_stitch": missing_stitch,
    "extra_inc": extra_inc,
    "impossible_increase": impossible_increase,
}


def _known_gap(kind, spec, row):
    """Where the count check is known to be blind (see README)."""
    if kind == "extra_inc":  # an extra stitch only shows on the NEXT row, never in the last
        return True
    if kind == "extra_stitch" and spec.mode == "rows":  # flat rows: same blind spot
        return True
    return spec.start == "chain" and row == 1  # stitches worked into the foundation chain


def inject(case, kind, rng) -> dict | None:
    """A broken copy of `case`, or None if this kind cannot be applied to it."""
    spec = copy.deepcopy(case["spec"])
    stated = list(case["stated"])
    n = len(spec.rows)
    rounds = list(range(2, n + 1))  # round 1 is never changed
    rng.shuffle(rounds)
    for r in rounds:
        if kind == "missing_round":
            if r == n:  # losing the last round leaves a shorter, valid pattern
                continue
            new = copy.deepcopy(spec)
            del new.rows[r - 1]
            new_stated = stated[: r - 1] + stated[r:]
        else:
            row = MUTATIONS[kind](spec.rows[r - 1])
            if not row:
                continue
            new = copy.deepcopy(spec)
            new.rows[r - 1] = row
            new_stated = stated
        out = make_case(f"{case['id']}+{kind}@{r}", case["family"], new, case["style"],
                        new_stated, kind, _known_gap(kind, new, r))
        if out["expected"]["break_row"] == r:  # the arithmetic must agree with where we broke it
            return out
    return None


def injected_cases(cfg, bases) -> list[dict]:
    rng = random.Random(f"{cfg['seed']}:inject")
    out = []
    for kind in cfg["injections"]["types"]:
        pool = list(bases)
        rng.shuffle(pool)
        made_n = 0
        for base in pool:
            if made_n >= cfg["injections"]["per_type"]:
                break
            case = inject(base, kind, rng)
            if case:
                out.append(case)
                made_n += 1
    return out
