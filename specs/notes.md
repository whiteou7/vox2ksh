# Notes: `.vox` buttons and lasers to `.ksh`

Code: [`../scripts/notes/`](../scripts/notes/). Formats: [`vox_format.md`](vox_format.md), [`ksh_format.md`](ksh_format.md). Numbers and examples: [`evidence/notes.md`](evidence/notes.md).

This covers BT, FX and laser notes, plus the BPM and time signatures that set up the grid.

## Buttons

Every vox tick is a whole multiple of the ksh line count, so button conversion loses nothing. Each measure picks its own line count as the gcd over its events. BT: `1` is a chip, `2` a hold. FX: `2` is a chip, `1` a hold. The chart ends at the last real event, not at `#END POSITION`, which often runs well past the last note.

## Lasers

Vox lasers are pre-sampled curves, sometimes as fine as 1/64 of a measure. ksh v1 can only join points with `:` or a slam, so each curve is thinned in two steps: Douglas-Peucker, then a minimum-spacing pass. All of it lives in `laser_curves.py`.

* Width: the vox wide flag becomes `laserrange_l`/`laserrange_r=2x`.
* Continuity: two non-slam points can never sit closer than a 24th note, or ksh reads them as a slam (its cutoff is 1/32). The limit is a note value, not a fraction of the measure.
* Real same-tick slams are kept. By default the slam ends `SLAM_GAP_FRAC` (a 32nd note) after it starts, as in hand charts (`--no-slam-gap` turns this off). In a dense chain with less room, the end backs off to one tick before the collision.
* A 32nd-note slam can't be written in ksh. `Run.tight` flags it.

When two runs meet on one tick, that's a handoff, not a slam. The runs are kept `MIN_RUN_GAP_TICKS` apart so a `-` row fits between them.

## Preview offset

Nothing in the game data gives `po=` or `plength=`. The preview is a separate pre-cut file, `<folder>_pre.s3v`, and nothing records where it was cut from. `preview_offset.py` recovers the offset by normalised cross-correlation of the clip against the track.

* It works for nearly every song. A few score low because their preview was cut from a different render of the same passage, and `MIN_NCC = 0.5` rejects those.
* Clip length is measured. Almost all clips are about 10 s with a fade, but three recent songs are 20 s with none. `plength` is rounded to 10 ms.
* Always correlate against the game's own `.s3v`, never a render.
* On any failure the chart gets `po=0 plength=0`, which KSM treats as absent.
* The CLI leaves this off (`--preview` enables it). The GUI turns it on.

`preview_offset.py --patch <folder>` rewrites `po=` and `plength=` in existing charts by editing only those lines, so the BOM, line endings and field order survive. A missing field is appended to the header.

## Checking

The `notes-refcheck` skill compares note, hold and laser-point counts against hand-made reference pairs. Button and laser-run counts match almost exactly, and laser points land close. The references are v1, so only v1 is checked. The constants tuned against it are `RDP_TOL` and `min_gap_frac`.

## KSH v2

Only `laser_l_curve` and `laser_r_curve` are implemented (`--ksh-version 2`). Everything else `ksh_format.md` marks "(Not supported in KSM v1.xx)" is still missing: `title_translit`, `artist_translit`, `chokkakuse` with a filename, `scroll_speed`, `rotation_deg` and the other `*_curve` options. Every `*_curve` option takes `"<a>;<b>"`, floats in 0..1.

One option covers one segment, from its laser point to the next. The segment is a quadratic bezier whose control point `(a, b)` is normalised within the segment, and `a == b` draws a straight line. None of this has been checked against a KSM v2 build.

* A multi-point run needs one option per segment, and a reversal ends an option's reach.
* A parabola can't change the sign of its curvature, so one segment can't draw an S. Splitting at the inflection fixes it (`0.37;0.00` and `0.63;1.00` for smoothstep) and cuts the error about 12x. An unsplit fit is barely better than a straight line.
* Vox `C7` tags generated points and isn't a renderer instruction. Type 0 rows are the real control points and the rest are pre-sampled fill, so the shape is already in the points and the v2 path ignores C7.

`laser_curves.py` ("ksh v2: laser curves", through `build_runs(curves=True)`) re-fits the curve instead of translating it:

* `decimate_segment_curved` replaces `decimate_segment`. Slam placement, width, run separation and the minimum gap don't change.
* Subdivision tries a straight join, then one curve. If neither fits, it splits at a turning point when the minimum-gap window has room, otherwise at the inflection (only if there's no reversal), otherwise at the worst-fitting point.
* `_curve_or_none` writes a curve only when the chord misses by more than half a laser step and the curve beats it by at least a quarter step.
* Curves are offered only where every gap is a 32nd note or shorter (`CURVE_LEG_FRAC`). A parabola can thread sparse authored points exactly while bowing anywhere between them.

Over the whole corpus, v2 writes fewer laser points than v1 and tracks the arcade's polyline much more closely. Authored staircases at 24th-note spacing survive point for point. Below one laser step, shapes get flattened, where v1's tighter `RDP_TOL` keeps more of them. `ver=` stays `171`.

## Bugs found and fixed

All of these turned up on charts outside the original 30-chart matched set and were checked against the full reference aggregate.

1. `shared/vox_parser.py` dropped the data in `#END POSITION`.
2. A fast curve tail could put its last point on ksh's slam cutoff and draw a slam nobody authored.
3. A same-tick slam on a run boundary lost its endpoint and drew a diagonal. The fix was only half right; see 11.
4. The min-gap pass could keep a near-extremum instead of the true peak.
5. A slam's end landed on the next free tick, a hairline compared with hand charts. It now uses `SLAM_GAP_FRAC`, checked against the next run's true start.
6. v2: a curve fitted over sparse linear points invented curvature. The fix was `CURVE_LEG_FRAC` plus scoring against the polyline. The metric shared the code's blind spot, so the bug stayed invisible until the ground truth changed from the vox points to the polyline through them.
7. v2: the inflection rule fired on stretches too sparse for a curve. It now uses the same density test.
8. v2: a split too close to an end was dropped, and a legal split went with it. It's now moved instead.
9. v2: turning points were thinned left to right, so room went to the wrong reversal. It now keeps the one furthest from the chord.
10. The minimum spacing was a fraction of the measure, not a note value, and was wrong in both directions outside 4/4 (6 ticks in 3/4, 82 in a 41-beat measure). It's now `whole_note // min_gap_frac`. 4/4 charts don't move.
11. Two sections handing off on one tick came out as a phantom slam. Ending a section costs a `-` row, so the two need to be two ticks apart, which `_separate_runs` now ensures. A jump that rounds to the same ksh step needs only one tick. Still open: chained same-tick stacks of three or more points can produce non-monotonic ticks.
12. The beat column of a `measure,beat,cell` timing was read as a quarter note. A beat is one denominator unit (`res * 4 / den` cells, so 12 in 15/16), so events past the first beat of a non-`/4` measure landed late. Every button category improved. `vox_format.md` already had this right. `render_chart.py` had the same bug; see `audio_engine.md` §5.3b.
