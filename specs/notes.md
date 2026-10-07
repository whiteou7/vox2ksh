# Notes: `.vox` buttons and lasers to `.ksh`

Code: [`../scripts/notes/`](../scripts/notes/). Formats: [`vox_format.md`](vox_format.md), [`ksh_format.md`](ksh_format.md).

Covers BT/FX/laser notes, plus the BPM and time signatures needed for the grid. Sound-fx parameters are in the audio track, roll/swing is in `camera.md`, `#TRACK AUTO TAB` is skipped. Header metadata is placeholder unless the caller passes `meta` to `convert()`; the GUI fills it from `music_db.xml`.

## Buttons

Vox ticks are always a whole multiple of the ksh line count, so the mapping is exact. Each measure picks its own line count by gcd over its events. BT: `1` chip, `2` hold. FX: `2` chip, `1` hold. Chart length is the last real event, not `#END POSITION`, which often runs past the last note.

## Lasers

Vox lasers are pre-sampled curves, as fine as 1/64 of a measure. ksh v1 only has points joined by `:` or a slam, so each curve is decimated (Douglas-Peucker, then a minimum-spacing pass). All in `laser_curves.py`.

* Width: the vox wide flag maps to `laserrange_l`/`laserrange_r=2x`.
* Continuity: two non-slam points must never be closer than a 24th note, or ksh reads a slam (its cutoff is 1/32). This is a note value, not a fraction of the measure (see bug 10).
* Real same-tick slams are kept. By default the slam ends `SLAM_GAP_FRAC` (1/64 measure) after its start, like hand charts (`--no-slam-gap` disables it). If a dense chain leaves less room, the end backs off to one tick before the collision.
* A 32nd-note slam can't be represented. `Run.tight` flags it.

A same-tick boundary between two runs is a handoff, not a slam. The runs are kept `MIN_RUN_GAP_TICKS` apart so a `-` row fits between them (bug 11).

## Preview offset

`po=` and `plength=` have no source in the game data. The preview is a separate pre-cut file, `<folder>_pre.s3v`, and nothing records where it was cut from. `preview_offset.py` finds the offset by normalised cross-correlation of the clip against the track.

Over 2184 songs the best lag scores a median 0.973 (5th percentile 0.905, 1st 0.831). `MIN_NCC = 0.5` refuses 6, all under 0.45. Scores stay below 1.0 because the game fades the clip in and out. `po` is the start of the clip, fade included.

* Clip length is measured, not assumed. 2181 clips are about 10 s and faded. Three (`2120_hbfs_daffpunk`, `2168_garasuno_kneesormx_korsk`, `2170_icbmoflove_odenpa`) are 20 s starting at exactly 30.000 s with no fade. `plength` is rounded to 10 ms.
* Some previews come from a different render of the same passage (`2336_ticktackchikupa_risyuu` scores 0.698, same music mixed differently), hence the low threshold. The lag is still right there. Always correlate against the game's own `.s3v`, never a render.
* `2229_kamui_tjhangneil` has a 544-byte `_pre.s3v` stub that ffmpeg refuses, so it gets no answer.
* Any failure leaves `po=0 plength=0`, which KSM treats as absent.
* Off by default on the CLI (`--preview`), on in the GUI.

`preview_offset.py --patch <folder>` rewrites `po=`/`plength=` in existing charts by editing just those lines, so BOM, line endings and field order survive. A missing field is appended to the header.

## Checking

The `notes-refcheck` skill compares note, hold and laser-point counts against 30 hand-made reference pairs. Button and laser-run counts match almost exactly; laser points are within about 4%. v1 only, since the references are v1 and v2 writes about 30% fewer points. Tuned constants: `RDP_TOL`, `min_gap_frac`.

## KSH v2

Only `laser_l_curve`/`laser_r_curve` are implemented (`--ksh-version 2`). The rest of what `ksh_format.md` marks "(Not supported in KSM v1.xx)" is not: `title_translit`, `artist_translit`, `chokkakuse` with a filename, `scroll_speed`, `rotation_deg`, and the other `*_curve` options. All `*_curve` options take `"<a>;<b>"`, floats in 0..1.

### Curve model

One option covers one segment, from its laser point to the next. The segment is a quadratic bezier with control point `(a, b)` normalised within the segment. `a == b` is straight. Not verified against a KSM v2 build.

* One option, one segment, so a multi-point run needs one per segment, and a reversal ends an option's reach.
* A parabola can't change curvature sign, so one segment can't draw an S. Fitting smoothstep:

| fitted as | `<a>;<b>` | rms |
|---|---|---|
| one segment | degenerate | 0.0652 |
| first half | `0.37;0.00` | 0.0051 |
| second half | `0.63;1.00` | 0.0051 |

A straight line scores 0.0682, so an unsplit S buys almost nothing. Splitting at the inflection cuts the error 12.8x.

### What vox C7 is

Over all 2447 v12/v13 charts, the gaps inside runs for every non-zero C7 (2, 3, 4, 5) have a median of 3/192 of a measure, p99 4/192. Type 0 gaps are a quarter note, 95% wider than 1/32. So type 0 rows are real control points and the rest are pre-sampled fill. C7 is a provenance tag, not a renderer instruction; the shape is in the points. The v2 path doesn't read it.

Monotonic stretches of 8 or more points, averaged, fit these curves:

| C7 | shape | best `<a>;<b>` |
|---|---|---|
| 4 | sine ease out | `0.6;1.0` |
| 5 | sine ease in | `0.4;0.0` |

Types 2 and 3 average to near-linear because instances differ (type 2's Hermite derivatives aren't in the file), so they need per-segment fits.

### The fit

`laser_curves.py` "ksh v2: laser curves", via `build_runs(curves=True)`. It re-fits rather than translates:

* `decimate_segment_curved` replaces `decimate_segment`. Slam placement, width, run separation and the minimum gap are unchanged.
* Subdivision tries a straight join, then one curve. If that misses, it splits at a turning point if the minimum-gap window has room, else at the inflection (only if there's no reversal), else at the worst-fitting point.
* `_curve_or_none` writes a curve only if the chord misses by more than half a laser step and the curve beats it by at least a quarter step.
* Fits sweep `a` coarse then fine, solving `b` in closed form, scored on the two-decimal values the option can carry.
* Curves are only offered where every gap is a 32nd note or shorter (`CURVE_LEG_FRAC`). Sparse authored points can be threaded exactly by a parabola that bows anywhere between them.

Over all 8255 charts, scored against the polyline the arcade draws: 1,492,920 points become 1,334,733 (-10.6%) with 49,116 curve options, and rms error drops from 0.423 to 0.185 laser steps. Over MXM/INF only, -29% points. Authored staircases and zigzags at 24th-note spacing survive point for point. Below one laser step shapes are flattened, where v1's tighter `RDP_TOL` keeps more. `ver=` stays `171`.

## Bugs found and fixed

All verified on the full reference aggregate (649 charts) and found on charts outside the original 30-chart matched set.

1. `shared/vox_parser.py` dropped `#END POSITION`'s data (an `#END` prefix check also matched that tag).
2. A fast curve tail could land its last point exactly on ksh's slam cutoff, drawing an unintended slam.
3. A same-tick slam on a run boundary lost its endpoint and drew a diagonal. The fix was half right; see 11.
4. The min-gap pass could keep a near-extremum instead of the true peak, shifting turning points early. Took three attempts.
5. A slam's end landed on the next free tick, a hairline next to hand charts. Now `SLAM_GAP_FRAC`. A first version could run a slam past the next run's start and swallow the gap `LaserLane.anchors()` needs (`gryphone/mxm` laser runs 204 to 155). Now checks the next run's true start.
6. v2: a curve fitted over sparse linear points invented curvature (`2010_xroinrmx_xi_5m` tick 6708, 24 steps off). 261 curves were affected, and the metric couldn't see it because it also scored at the vox points. Fixed by `CURVE_LEG_FRAC` and by scoring against the polyline. 261 cases down to 13, worst 24 to 4.2 steps. Lesson: the metric shared the code's blind spot.
7. v2: the inflection rule fired on stretches too sparse for a curve (`2242_hihouwaineat_shu_5m` tick 6504, 14 steps off). Now gated on the same density test.
8. v2: a split too near an end was dropped, taking a legal split with it (`2226_gryphone_etia` tick 12408, 14 steps off). Now moved instead.
9. v2: turning points were thinned left to right, so room went to the wrong reversal (`0653_konransyojo_kameria_4i` measure 56, 24.9 to 4.9 steps). Now picks the reversal furthest from the chord (`_most_deviant`).
10. The minimum spacing was a fraction of the measure, not a note value. In 4/4 it's a 24th note, but a 3/4 measure got 6 ticks (the slam cutoff itself) and `0536_chase_in_the_shine_penoreri_3e`'s 41-beat measure got 82, which flattened features 12 ticks apart (50 steps off, now 0). Now `whole_note // min_gap_frac`. 4/4 charts don't move. Aggregate: laser points 24.25 to 23.23 mean error, 48 charts better and 27 worse. All 27 are shorter-than-4/4 charts where the stricter gap drops points the charter kept. Corpus rms: v1 0.4231 to 0.4189, v2 0.1853 to 0.1533.
11. Two sections handing off on one tick came out as a phantom slam. Ending a section costs a `-` row, so two sections need two ticks apart, and bug 3's fix left one. Overlapping runs also made `run_at` drop a run outright (`0223_syonenha_sorawo_tadoru_toromaru_3e`). Fixed by `_separate_runs`, a backward sweep. A jump that rounds to the same ksh step only needs one tick, since separating those would invent a release and regrab (40 of 130 handoffs). Corpus: 66 phantom slams, 114 overlapped boundaries and 25 merged gaps go to zero. 27 of 28 visible jumps have a `-` in the hand chart. Aggregate: laser-run exact matches 94.0% to 94.5%, mean error 0.30 to 0.31, because hand charters merge more than vox does. Open: 322 runs with non-monotonic ticks from chained same-tick stacks of 3 or more points.
12. The beat column of a `measure,beat,cell` timing was read as a quarter note. A beat is one denominator unit (`res * 4 / den` cells, 12 in 15/16), so events past the first beat of any non-`/4` measure landed late (`2152_nemsysarena_tonarinoniwa_3e`). `vox_format.md` had it right. Across 8254 charts and 7,492,359 rows, no `beat` is at or above the numerator and no `cell` at or above `res*4/den`. 501 charts have a non-`/4` signature, 416 of them moved; the other 7751 are unaffected. Every button category improved with no chart worse: BT chip error 1.33 to 0.84, laser runs 0.31 to 0.15, laser points 23.29 to 21.19. Six charts now match their references exactly (`spear_of_justice/mxm` BT chips 469 to 505). `render_chart.py` had the same bug; see `audio_engine.md` §5.3b.
