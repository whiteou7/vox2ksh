---
name: notes-refcheck
description: Regression-test the .vox to .ksh notes conversion against the hand-made reference conversions. Use whenever anything under scripts/notes/ changes — convert.py, laser.py, decimation constants, grid/measure logic, slam handling — or when shared/vox.py parsing changes, and before calling any such change good. Also use when asked to "crosscheck the notes", "check the conversion" or "run the notes xcheck".
---

# Notes reference check

`scripts/notes/xcheck.py` converts every chart it can match to a hand-made reference `.ksh` under `scripts/shared/reference/ksh/`, and compares counts — bars, BT chips/holds, FX chips/holds, laser runs, laser points — on both sides. It is a structural comparison, not a diff: the references are hand conversions, so they are a strong signal about "is this the same chart" and a weak one about exact byte equality.

Python is `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`. Run everything from the `vox2ksh` directory.

## The one rule

**Measure before and after, over the whole matched set.** Laser decimation trades one category against another, so a change that looks like a clear win on three charts routinely loses on the aggregate. Four bugs in this converter were found on charts *outside* the matched set and each was only accepted after the full aggregate held.

## Procedure

### 1. Baseline

Baselines live in `output/refcheck/` (git-ignored). Reuse one only if it came from the pre-change tree.

```bash
git stash push -m notescheck-baseline && python scripts/notes/xcheck.py --csv output/refcheck/notes_before.csv ; git stash pop
```

Confirm the stash popped cleanly.

### 2. Iterate

For a single chart while developing:

```bash
python scripts/notes/xcheck.py --only <song-substring>
```

`convert.py <chart.vox> -o out.ksh` renders one chart if you need to read the output directly. A conversion that raises is counted as a failure, not a mismatch — check the "failed to convert" list, it is easy to miss under the aggregate.

### 3. Full run, after

```bash
python scripts/notes/xcheck.py --csv output/refcheck/notes_after.csv
```

### 4. Compare

```bash
python .claude/skills/notes-refcheck/compare.py output/refcheck/notes_before.csv output/refcheck/notes_after.csv
```

It prints, per category: mean and median absolute error before/after, exact-match percentage, how many charts improved versus regressed, and the charts that moved most.

### 5. Verdict

* **Buttons (bars, BT chip/hold, FX chip/hold) are exact by construction.** Vox ticks are always a whole multiple of the ksh line count, so any non-zero mean error here is a real bug — in the grid, the measure line count, or the parser — not an approximation. A regression in these categories blocks the change outright.
* **Laser runs should match almost exactly.** A moved run count usually means slam handling or run splitting changed.
* **Laser points are approximate** — decimation reproduces a curve's shape, not one charter's exact point choices, and ~4 % mean is the standing figure. Judge this category on the aggregate, and never at the cost of a button category.
* Charts that newly **fail to convert** are a blocking regression regardless of what the aggregate did.

Report each category as before → after with the chart split, then say plainly whether the change is adopted. If it improves laser points while moving any button category off exact, it is not a fix.

### 6. Check outside the matched set

The matched set is ~30 pairs; the corpus is 8107 charts. Before calling a fix done, convert a handful of charts that have no reference — including at least one with a non-48 `#BEAT RESOLUTION` and one with heavy laser curves — and confirm they still convert without raising. That is how the last four bugs were found.

## Recording the result

Add the finding to `specs/notes.md` — its "Bugs found and fixed" list is the record, and the tuned constants (`RDP_TOL`, `min_gap_frac`) live in `laser.py` with comments explaining what they were fitted against. If a constant moves, say what aggregate justified the move.
