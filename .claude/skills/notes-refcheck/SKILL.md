---
name: notes-refcheck
description: Regression-test the .vox to .ksh notes conversion against the hand-made reference conversions. Use whenever anything under scripts/notes/ changes — convert_notes.py, laser_curves.py, decimation constants, grid/measure logic, slam handling — or when shared/vox_parser.py parsing changes, and before calling any such change good. Also use when asked to "crosscheck the notes", "check the conversion" or "run the notes xcheck" or "check the notes".
---

# Notes reference check

`check_all_charts.py` converts every chart with a reference `.ksh` under `scripts/shared/reference/ksh/` and compares counts: bars, BT chips/holds, FX chips/holds, laser runs, laser points. The references are hand conversions, so this is a structural comparison, not a diff.

Python is `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`. Run from the `vox2ksh` directory.

**Rule: measure before and after, over the whole matched set.** Laser decimation trades one category against another, so a change that wins on three charts often loses overall.

## Procedure

1. Baseline. Reuse one in `output/refcheck/` only if it came from the pre-change tree.

```bash
git stash push -m notescheck-baseline -- scripts && python .claude/skills/notes-refcheck/check_all_charts.py --csv output/refcheck/notes_before.csv ; git stash pop
```

2. Iterate on one song. This prints our counts against the reference, split by lane, and writes the `.ksh` to `output/work`. It checks every difficulty in the reference folder unless `-d` picks one.

```bash
python .claude/skills/notes-refcheck/check_one_chart.py <song-substring> [-d mxm]
```

A conversion that raises counts as a failure, not a mismatch. Check the "failed to convert" list.

3. Full run after the change.

```bash
python .claude/skills/notes-refcheck/check_all_charts.py --csv output/refcheck/notes_after.csv
```

4. Compare.

```bash
python .claude/skills/notes-refcheck/compare_runs.py output/refcheck/notes_before.csv output/refcheck/notes_after.csv
```

## Verdict

* Buttons (bars, BT, FX) must stay exact. Any error there is a bug in the grid, line count or parser. A regression blocks the change.
* Laser runs should match almost exactly. A moved count usually means slam handling or run splitting changed.
* Laser points are approximate (about 4% mean error). Judge them on the aggregate, never at the cost of a button category.
* A chart that newly fails to convert blocks the change.

Report each category as before and after, then say whether the change is adopted.

## Outside the matched set

Only about 30 charts match. Before calling a fix done, convert a few charts with no reference, including one with a non-48 `#BEAT RESOLUTION` and one with heavy laser curves, and check they convert without errors.

## Recording the result

Add it to the "Bugs found and fixed" list in `specs/notes.md`. If a constant like `RDP_TOL` or `min_gap_frac` moves, say which aggregate justified it.
