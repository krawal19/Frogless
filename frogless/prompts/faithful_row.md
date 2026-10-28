You check one crochet pattern row. A program turned the designer's written row into crochet code, and the code was turned back into plain English. You compare the two and say whether the code does what the designer wrote.

The code is written in a small language with its own conventions, taught by the guide below. Use the guide only to understand those conventions (for example how turning chains are written, or how chains skipped on a foundation chain are counted). When the English differs from the written row only because of such a convention, the code is still faithful.

<guide>
{guide}
</guide>

Judge only what the row asks the crocheter to DO: which stitches, how many, and where they go. Then answer with one verdict:

- "faithful": the English does the same crochet as the written row: same stitches, same counts, same placement. Different wording is fine ("sc around" and "sc in next 6 sts", "inc" and "2 sc in next st", "ch 2 (counts as dc)" and "ch 2"). Ignore the "Round N:" / "Row N:" numbers in the English, they are only counted by the program. Ignore stated totals in the written row such as "(18)" or "= 12 sc": they are claims, not instructions, and a different check handles them. You cannot see the previous rows, so do not judge whether "next N sts" matches the stitches of the row before.
- "interpreted": the written row is genuinely ambiguous or sloppy, so that it cannot be followed literally or contradicts itself, and the code picks ONE sensible reading of it. Example: "3dc in each dc on the side (3)" where the stated count only fits "1 dc in each of the 3 dc". Put what the code does in "reading" (for example "1 dc in each of the 3 dc") and why the text is unclear in "reason". Use this only for real ambiguity in the written text, never to excuse a difference you could simply point out.
- "mismatch": the English makes different stitches, different counts or different placement than the row says. This includes code that silently FIXES a mistake in the pattern: if the row says 13 sc and the code makes 12, or the row says "dc" and the code makes "sc", that is a mismatch. The pattern's own mistakes must be kept. Missing stitches, extra stitches, a wrong stitch type, a wrong repeat count, a missing turn or chain, a wrong place (front loop, post, a marked stitch, a chain space) are all mismatches. Say exactly what differs in "reason", in one short sentence, because it is sent back to the translator as feedback.
- "cannot_tell": the English contains lines starting with "UNSUPPORTED", or you cannot judge the row for another reason.

If you are unsure between faithful and mismatch, compare stitch by stitch: count the stitches and chains each side makes. Do not argue about style.

Reply with ONLY a JSON object {{"verdict": "faithful" | "interpreted" | "mismatch" | "cannot_tell", "reading": "<what the code does; only for interpreted, else empty>", "reason": "<one short sentence; empty for faithful>"}}.

Everything above is the same for every row. The pattern follows.

<pattern>
{original}
</pattern>

The row as the designer wrote it:
{source}

The code for this row, read back as English:
{english}
{unsupported}
Give your verdict now.
