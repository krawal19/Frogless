"""Wrapping the last side of a round that starts in a corner space.

A square worked in rounds starts each round in a corner space of the round below (`(2dc,2ch,2dc)@A,...`), so the
round's last side runs on past the end of that line and comes back round onto the stitches before its first chain
(its starting `ch 3`, the first dc). The language wants those last stitches written as their own item
(`...,2dc,dc@S`, with `S` labelling the first stitch of the line below). A side written as one plain `3dc` is
refused: the stitches land on the closing slip stitch of the round below and the stitch before its first chain is
left over ("leaves 1 stitch unworked"). Nothing in the text is wrong there; the wrap is a notation detail.

complete_wraps() writes the wrap out: the stitches that remain after the last corner stay a plain run, the rest
become `Ndc@W` on the stitches before the first chain. It does so only where all of this holds:
- the row starts with a group worked into a label that sits on a chain of the line below (a corner space);
- the line below ends with a slip stitch (the round's join) and has plain stitches before its first labelled chain;
- the row's last plain run of one stitch (straight after its last `@` group) is longer than the stitches the line below has after
  its last labelled chain, but not longer than those and the ones before its first chain together.
A run that overshoots even that is left as it is, and the engine reports it. The same number of stitches is written
as before: only where the last ones go changes.
"""

import re

from .spaces import Group, Leaf, SpaceError, _expand, _leaves, _parse, _text

PLAIN = {"sc", "hdc", "dc", "dtr", "ttr", "trtr", "tr"}
_LEAF = re.compile(r"^(?P<n>\d*)(?P<kind>[a-z]+\d*[a-z]*)(?P<labels>(?:\.\w+)*)(?P<at>@\S*)?$")
_LABEL = re.compile(r"^@([A-Za-z_]\w*)$")


def _parts(leaf: Leaf):
    """(count, kind, labels, "@..." or "") of a stitch or chain written as one item, or None."""
    m = _LEAF.match(leaf.text)
    return (int(m["n"] or 1), m["kind"], [x for x in m["labels"].split(".") if x], m["at"] or "") if m else None


def _plain_stitches(leaves: list[Leaf]) -> int | None:
    """How many plain stitches `leaves` make (chains do not count), or None if one is not plain (an increase...)."""
    total = 0
    for leaf in leaves:
        p = _parts(leaf)
        if p is None or p[1] in ("ss", "sk"):
            return None
        if p[1] != "ch":
            if p[1] not in PLAIN:
                return None
            total += p[0]
    return total


def _wrapped(below: list, row: list, taken: set[str]) -> list | None:
    """The row's items with its last run wrapped, or None when this is not the case described above."""
    leaves = list(_leaves(below))
    parts = [_parts(lf) for lf in leaves]
    if not leaves or parts[-1] is None or parts[-1][1] != "ss":
        return None
    chains = [k for k, p in enumerate(parts) if p and p[1] == "ch" and p[2]]
    start = row[0] if row else None
    corner = _LABEL.match(start.suffix) if isinstance(start, Group) else None
    if not chains or not corner or not any(corner[1] in parts[k][2] for k in chains):
        return None
    ahead, behind = _plain_stitches(leaves[:chains[0]]), _plain_stitches(leaves[chains[-1] + 1:-1])
    if not ahead or behind is None:
        return None
    last = max((k for k, it in enumerate(row) if isinstance(it, Group) and it.suffix.startswith("@")), default=None)
    if last is None or last + 1 >= len(row) or not isinstance(row[last + 1], Leaf):
        return None
    run, end = [], last + 1  # the plain stitches straight after the last corner group
    while end < len(row) and isinstance(row[end], Leaf) and (p := _parts(row[end])) and p[1] in PLAIN and not p[2] and not p[3]:
        run.append(p)
        end += 1
    kinds = {p[1] for p in run}
    count = sum(p[0] for p in run)
    if len(kinds) != 1 or not behind < count <= behind + ahead:
        return None
    kind = kinds.pop()
    first = parts[0]
    if first and first[2]:
        name = first[2][0]
    else:
        name = next(f"W{i}" for i in range(1, 1000) if f"W{i}" not in taken)
        taken.add(name)
        leaves[0].text += "." + name
    wrap = count - behind
    items = ([Leaf(f"{behind if behind > 1 else ''}{kind}")] if behind else [])
    items.append(Leaf(f"{wrap if wrap > 1 else ''}{kind}@{name}"))
    return row[:last + 1] + items + row[end:]


def complete_wraps(code: str) -> str:
    """The code with the last side of each round that starts in a corner space written out as a wrap (see above).
    Code that has no such round comes back unchanged."""
    lines = code.split("\n")
    rows = [i for i, line in enumerate(lines) if line.strip()]
    taken = set(re.findall(r"\.(\w+)", code)) | {"R0"}
    for pos in range(1, len(rows)):
        j, i = rows[pos - 1], rows[pos]
        try:
            below, row = _expand(_parse(lines[j].strip())), _expand(_parse(lines[i].strip()))
            wrapped = _wrapped(below, row, taken)
        except SpaceError:
            continue
        if wrapped:
            lines[j], lines[i] = _text(below), _text(wrapped)
    return "\n".join(lines)
