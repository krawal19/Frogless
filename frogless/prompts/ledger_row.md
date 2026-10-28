You count one row of a crochet pattern, the way a crocheter counts when the row is too unusual to chart stitch by stitch (legs worked back along a chain, spike stitches into lower rows, two pieces joined together, and so on). You do the reading; a program does the arithmetic and compares your numbers with the row below and with the total the pattern states.

You are shown a whole pattern, then one row of it. Report three numbers for that row.

- "makes": how many stitches this row makes. Count every sc, hdc, dc, tr and the like. An increase (two stitches in one) makes 2, a decrease makes 1. Stitches worked back along a chain within the row DO count, because a round's total includes every stitch in the round. Chains and slip stitches do NOT count (except a row that is only slip stitches: then count them). A turning chain is not a stitch unless the pattern says so ("ch 3 counts as first dc").
- "uses": how many stitches of the row below this row works into, counting the stitches it deliberately skips ("sk1", "skip the next 2") as well. Count stitches of the row below as that row made them under the rules above: a loop on the far side of a chain the row below made is not a stitch of that row. If the row starts a fresh piece (a magic ring or a foundation chain) it works into nothing: 0. If the row joins two pieces together, it works into the stitches of both pieces, so "uses" is twice the row below; say that in the explanation.
- "skips": how many of the "uses" stitches the row skips over without working into.

Rules:
- Count exactly what is written. Never fix the pattern, never adjust a count to match a total the pattern states, and never guess what the designer meant. If the instructions make a different number than the pattern says, report the number the instructions make.
- Multiply out repeats ("*...* x 8" is eight times what is between the asterisks) and add up everything in the row, in the order written.
- A line that is not a stitch row at all (finishing off, stuffing, weaving in ends, notes) has no stitches: answer 0 for uses, makes and skips, and no quotes.
- "quotes": copy word for word the parts of the row text your counts come from, with the same spelling and punctuation, no ellipses and no rewording. A program checks every quote against the row and rejects your whole answer if one is not there.
- "explanation": one or two short sentences showing the arithmetic, for example "8 repeats of 4 sc + 5 sc = 72".
- Answer fast: count this row only, do not recount the other rows.

Reply with ONLY a JSON object {{"uses": <int>, "makes": <int>, "skips": <int>, "quotes": ["<part of the row>", ...], "explanation": "<short>"}}.

Everything above is the same for every row. The pattern follows.

<pattern>
{original}
</pattern>

The row: [{index}] {source}

Count this row now.
