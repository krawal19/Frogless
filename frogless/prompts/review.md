You review one crochet pattern. A program turned each written row into crochet code for a crochet engine, and the engine checks the stitch counts of the whole pattern. The guide below teaches the code language.

<guide>
{guide}
</guide>

You will be shown the whole pattern, then every row as "[number] written text" with the row's current code ("?" where it has none), and what the program's check currently finds. You take one side of an argument about this pattern; your side is given below. Then you answer for the whole pattern at once.

How to answer. Reply with ONLY a JSON object {{"summary": "<one or two sentences: your case for the whole pattern>", "rows": [<entry>, ...]}}. Each entry is {{"row": <the [number]>, "quote": "<part of the row's written text>", "verdict": "ok" | "reading" | "fix", "code": "<engine code>", "explanation": "<one short sentence>", "fixed_text": "<text>"}}.
- Only rows that must differ from their current code (or, for a fix, rows whose written text must change) need an entry. Leave every other row out.
- "code" is engine code for the WHOLE row, in the language of the guide, or "same" to keep the row's current code (for example when only the written text changes).
- "quote" is copied word for word from that row's written text as listed in <rows> (the pattern above may be spelled a little differently), with the same spelling and punctuation, no ellipses and no rewording: the part your entry is about. A program checks every quote against the row and throws away an entry whose quote is not there.
- "fixed_text" is used only with the verdict "fix": the whole row as it should read after the fix, including its "Round 4:" label. For every other verdict it is "".
- The code must really do what the text says. A program re-checks your whole answer: the engine must accept the code, the stitch counts must fit the totals the pattern states, and a second reader compares each changed row's code with its words.
- Rows shown with "?" have no code yet: give them code if you can. A row marked "(already read as: ...)" was read that way on purpose, the way the designer writes the other rows (for example a number beside a side may be that side's total, counting the corner stitches); keep that convention in the rows you change.
- Answer fast: do not recount every row, look at what the check found and the rows around it.

{task}

Everything above is the same for every question. The pattern follows.

<pattern>
{original}
</pattern>

<rows>
{rows}
</rows>

What the program's check currently finds: {finding}
{feedback}
Give your answer now.
