"""An oval: a row that goes round the end of the foundation chain and back along its other side.

The language writes the way back as one group worked into a label planted on the FIRST chain of the foundation
chain: `ch.A,12ch` then `sk,11sc,sc3inc,(10sc,sc2inc)@A`. The label is a notation detail, the reading is the
same without it: label_foundation() puts it on the first chain when the row has the group but the foundation
chain does not carry the label (`13ch`, or `13ch.A` where the label would sit on every chain).
"""

import re

_FOUNDATION = re.compile(r"^(?P<n>\d*)ch(?:\.(?P<label>\w+))?$")
_GROUP_AT = re.compile(r"\)@([A-Za-z_]\w*)(?![\w\[])")


def label_foundation(code: str) -> str:
    """The code with the foundation chain's first chain labelled, when the row after it works a group into a
    label that nothing defines or that sits on the whole chain. Code without that comes back unchanged."""
    lines = code.split("\n")
    rows = [i for i, line in enumerate(lines) if line.strip()]
    if len(rows) < 2:
        return code
    first, second = rows[0], rows[1]
    m = _FOUNDATION.match(lines[first].strip())
    if not m or int(m["n"] or 1) < 2:
        return code
    wanted = _GROUP_AT.findall(lines[second])
    if len(set(wanted)) != 1 or wanted[0] == "R0":
        return code
    name, label = wanted[0], m["label"]
    defined = set(re.findall(r"\.(\w+)", "\n".join(l for i, l in enumerate(lines) if i != first)))
    if name in defined or (label and label != name):
        return code
    lines[first] = f"ch.{name}," + (f"{int(m['n']) - 1}ch" if int(m["n"]) > 2 else "ch")
    return "\n".join(lines)
