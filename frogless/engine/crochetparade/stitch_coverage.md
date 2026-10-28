# Stitch coverage: common specialty stitches vs CrochetPARADE

Which common crochet stitches and techniques the engine can express.

- ✅ supported: the engine accepts the code shown, and the count behaviour was checked with `get_engine().check()`.
- ◐ approximated: stitch and chain counts come out right, but the shape (or which row it reaches into) is not modelled.
- ❌ not expressible: no honest engine equivalent, so a translation should be `# CANNOT: <reason>`.

All ✅ stitch names are listed in the `stitches` block of `notation_guide.md`, which `tests/test_notation_guide.py` checks. Tally of the two stitch tables: 26 ✅, 15 ◐, 6 ❌. The technique table at the end is separate.

Column "Engine code" shows what to write for one stitch worked into one stitch of the previous line, unless the note says otherwise.

## Basics

| Stitch | What it is | Status | Engine code and notes |
|---|---|---|---|
| Chain (ch) | Loop pulled through the loop on the hook; builds the base or a gap | ✅ | `ch`, `5ch`. Never worked into, so it counts 0 |
| Slip stitch (sl st) | Hook through the stitch, one pull through both loops; barely any height | ✅ | `ss`. Counts 0 in rounds, joins with `,ss` |
| Single crochet (sc) | Short, dense stitch | ✅ | `sc` |
| Half double crochet (hdc) | Middle-height stitch, yarn over before inserting | ✅ | `hdc` |
| Double crochet (dc) | Taller stitch with two pull-throughs of two loops | ✅ | `dc` |
| Treble crochet (tr) | Yarn over twice, taller than dc | ✅ | `tr` |
| Double treble (dtr) | Yarn over three times, one step above tr | ✅ | `dtr` |
| Triple treble (trtr, ttr) | Yarn over four times, one step above dtr | ✅ | `trtr` (`ttr` is invalid) |
| Magic / slip ring | Adjustable loop that the first round is worked into | ✅ | `ring.R0` then `(6sc)@R0` |
| Increase (inc) | Several stitches in one stitch | ✅ | `sc2inc`, `dc3inc`, `tr6inc`; any N works (`dc9inc`) |
| Decrease / together (dec, tog) | Several stitches joined into one | ✅ | `sc2tog`, `hdc2tog`, `dc3tog`, `dtr2tog`; loop and post forms exist (`scbl2tog`, `fpdc2tog`) |
| Skip (sk) | Pass over a stitch without working it | ✅ | `sk`, `2sk`; still uses up a stitch of the previous line |
| Front / back loop only | Work only under the loop nearest or farthest from you | ✅ | `scbl`, `scfl`, `hdcbl`, `dcfl`, `trbl`, `dtrfl`, `ssbl`, ... |
| Reverse single crochet (rsc) | Single crochet worked backwards across the row | ✅ | `rsc`, `rscbl`, `rscfl` |
| Working into the chain | Skip the first chains, insert the hook into each chain after | ✅ | Pattern rules are in the guide: `sk,14sc` for Ch 15. Working in the back bar only does not change counts, so it is ignored |
| Turning chain | Chain at the start of a row to reach the right height | ✅ | Follows the guide's per-stitch turning chain rules |
| Side marker (RS / WS), colour change, MC / CC, measurements | Notes about which side faces you or which yarn to use | ✅ | Ignored: no effect on counts |

## Specialty stitches

| Stitch | What it is | Status | Engine code and notes |
|---|---|---|---|
| Front / back post (fpsc bpsc fphdc bphdc fpdc bpdc fptr bptr) | Stitch worked around the upright post of a stitch below, from front or back | ✅ | `fpdc`, `bpdc`, `fptr`, `bptr`, `fpsc`, `bpsc`, `fphdc`, `bphdc`; also `fpdc2tog`, `fpdc2inc` |
| Front post treble + sc combo (fptr-sc) | Post treble followed by an sc to make a ripple | ◐ | Write as two stitches, `fptr,sc` |
| Front post tr 2 together, split (fptr2tog) | Two post trebles two stitches apart, joined into one stitch | ◐ | `fptr2tog,sk` consumes three stitches; the pattern's own stitch count decides how many `sk` |
| V-stitch (V-st) | Two stitches with a chain between, all in one stitch | ✅ | `dc,ch,dc@[@]`; any base stitch: `tr,ch,tr@[@]`. Consumes one stitch |
| Shell | A fan of several dc, usually with chains between groups, in one stitch or space | ✅ | `dc5inc` for 5 dc in a stitch; with a chain gap `dc2inc,2ch,dc2inc@[@]`. Consumes one stitch (check: `2*[2sk,dc5inc,2sk,sc]` on 12 sts is 12 to 12) |
| Picot (3-chain) | Small bump: chain 3, slip stitch back into the base stitch | ✅ | `picot3`. Consumes 0 itself, so put it after a stitch: `sc,picot3` |
| Picot (other sizes, version two with back bar) | Same bump with another chain count, or the back-bar join | ◐ | Use `picot3`, or `DEF: p4 = 4ch, ss@1[%,%-5]` (the engine accepts a DEF line, but Frogless's one-line-per-row format has no place for it) |
| Bobble | Several unfinished stitches in one stitch closed together | ✅ | `dc3bobble`, `dc4bobble`, `dc5bobble`, `tr4bobble`. No other sizes |
| Popcorn (pc) | A group of full stitches in one stitch, then the first and last joined to pop out | ✅ | `dc3pc`, `dc4pc`, `dc5pc`. Popcorn of other sizes or stitch types: nearest size, flagged as approximate |
| Reverse popcorn (rpc) | Popcorn worked on the wrong side so it shows on the right side | ◐ | Same code as popcorn; the side it pops to is not modelled |
| Puff stitch | Several half-finished loops in one stitch pulled through at once | ✅ | `hdc3puff`, `hdc4puff`, `hdc5puff` (hdc-based only; a puff of another size or base stitch is ◐) |
| Cluster in one stitch (cl, 3-dc cl, 4-dc cl) | Several dc started in one stitch and closed together | ◐ | `dc3bobble` / `dc4bobble` for the same shape; counts match (one stitch in, one out) |
| Treble cluster (tr cl) | Same with treble stitches | ◐ | `tr4bobble` is the only tr form; legs differ, counts match |
| Cluster across stitches | Several stitches each started in a different stitch, closed together | ✅ | `dc3tog`, `dc4tog`, `tr2tog`; consumes N |
| Double / triple treble | Taller stitches, see Basics | ✅ | `dtr`, `trtr` |
| Extended sc / hdc / dc / tr (ext) | The stitch with one extra chain at its base, a bit taller | ◐ | `sc`, `hdc`, `dc`, `tr`: counts equal, the extra height is not modelled |
| Foundation sc / hdc / dc | Chain and first row made in one pass, no separate starting chain | ◐ | Use a normal chain and first row with the usual skips: N foundation sc = `<N+1>ch` then `sk,Nsc`; N foundation dc = `<N+2>ch` then `2sk,Ndc`. A row cannot start without a chain (`10sc` as line one is an engine error) |
| Chainless joins (sc, hdc, dc, tr join) | Start new yarn with a stitch instead of a slip knot and chain | ◐ | Write the starting stitch as the first plain stitch of the row |
| Stacked stitches (stacked hdc / dc / tr) | Stack of sc that stands in for a 2-, 3- or 4-chain turning chain | ◐ | `hdc`, `dc`, `tr` as the first stitch (counts as the first stitch like a real turning chain) |
| Linked stitches (ldc, ltr, beg ldc, beg ltr) | Stitch worked through the horizontal bar of the previous one instead of an open gap | ◐ | `dc`, `tr`; the join to the previous bar is not modelled |
| Split single crochet (split sc) | Hook goes between the two legs of the stitch below | ◐ | `sc`; the entry point is not modelled |
| Front cross / back cross (fcr, bcr) | Two dc swapped in order: skip one, dc in the next, then dc into the skipped stitch in front or behind | ◐ | `2dc` consumes the same two stitches; the crossing is lost. The stitch-swap needs `@[@+1]`-style attachments that are unreliable |
| Long sc / long dc, drop stitch | Stitch pulled long into a stitch several rows down | ◐ | `longsc`, `longdc`, `longtr` exist, but they attach to the previous line, not to the row below. Not in the guide's stitch list |
| Loop stitch (lp st) | Long loops on the front for a plush texture | ◐ | `sc` for counts; the loops are lost |
| Crocodile stitch | Scales built from V-stitches and post stitches worked down into earlier rows | ❌ | Needs post stitches around stitches several rows down; `# CANNOT: crocodile stitch` |
| Star stitch | Pulled-up loops across several stitches, closed into a star | ❌ | Several loops come from different stitches with a variable count; `# CANNOT: star stitch` |
| Surface slip stitch | Slip stitches worked on top of finished fabric, not a row | ❌ | No row to count against; `# CANNOT: surface slip stitch` |
| Love knot / Solomon's knot (lk, dlk) | Long pulled-up loop locked with a single crochet | ❌ | Not a chain or a stitch with a stable count; `# CANNOT: love knot` |
| Cables (crochet-techniques) | Post stitches that cross over each other | ❌ | Same stitch-swap as the cross stitches, but across many; `# CANNOT: cable` |
| Tunisian crochet | Loops kept on a long hook, worked in two passes | ❌ | Different construction; `# CANNOT: Tunisian` |

## Techniques that are not stitches

| Technique | Status | Note |
|---|---|---|
| Joining a new ball, blocking, felting, hook holding, left-handed help | ✅ ignore | No effect on counts |
| Colorwork, charted picture afghans | ✅ ignore | Colour change is not a stitch; counts come from the stitches |
| Reading patterns and stitch diagrams | n/a | Our job, not a stitch |
| I-cord, layered-edge slip stitch seam | ❌ | Not covered; use `# CANNOT` |
