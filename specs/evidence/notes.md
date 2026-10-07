# Notes evidence

The numbers behind [`../notes.md`](../notes.md).

## Preview offset

* Over 2184 songs the best lag scores a median 0.973 (5th percentile 0.905, 1st 0.831). `MIN_NCC = 0.5` refuses 6, all under 0.45.
* 2181 clips are about 10 s and faded (2154 round to 10000 ms, 27 to 9980). Three (`2120_hbfs_daffpunk`, `2168_garasuno_kneesormx_korsk`, `2170_icbmoflove_odenpa`) are 20 s starting at exactly 30.000 s with no fade, and score 0.995 to 0.998.
* The measurement runs at 11025 Hz mono (0.09 ms per lag step, about half a second per song, cached per song). It holds against the rendered `.ogg`: `0001_albida_muryoku_3e` gives 84393 ms either way, correlating 0.97 against the dry track and 0.80 against the FX render.
* A repetitive song can score nearly as well at a second lag (`0785_voltexes3_sota_fujimori`: 0.974 against 0.950). Both are the same passage, so the runner-up isn't gated on.
* Some previews come from a different render of the same passage. `2336_ticktackchikupa_risyuu` scores 0.698 overall and 0.734 over the unfaded middle at its peak lag; refining to 44100 Hz moves the lag one sample and doesn't raise the score. Its spectral centroid matches to 2 Hz (1601 against 1599), and the dry `.s3v` and both its rendered `.ogg`s peak at the same millisecond.
* The 6 refused songs score 0.235 to 0.448. `0630_critical_line_kradness` (0.316) and `1852_crystalia_djtotto` (0.339) beat their runner-up by only about 0.01.
* `2229_kamui_tjhangneil` has a 544-byte `_pre.s3v`; every other preview is at least 183 KB. 2187 of 2190 song folders carry a `_pre.s3v`.
* `ticktackchikupa_risyuu`'s EXH render fell under `MIN_NCC` while the answer was known good from the dry track, so the measurement always runs against the `.s3v`.

## Checking

The `notes-refcheck` skill matches 30 reference pairs (name matching shared with the audio check via `match_references.py`). Laser points land within about 4% mean. v2 writes about 30% fewer laser points, so scoring it against the v1 references would read as a 30% error. v2 is measured against the vox samples across the whole corpus instead.

## KSH v2 curve fitting

Fitting smoothstep (`t²(3-2t)`, a Hermite spline with zero end derivatives):

| fitted as | `<a>;<b>` | rms | laser steps |
|---|---|---|---|
| one segment, whole S | degenerate | 0.0652 | 3.3 |
| first half, renormalised | `0.37;0.00` | 0.0051 | 0.25 |
| second half, renormalised | `0.63;1.00` | 0.0051 | 0.25 |

"One segment" emits only the sweep's two endpoints with one option on the start; the split versions add a point at the inflection for a second option.

The unsplit fit is degenerate: smoothstep is symmetric, so `0.95;1.00` and its mirror `0.05;0.00` tie, and all 92 grid cells within 0.001 of the minimum have `|a - b|` in 0.03 to 0.08, so every candidate is near-straight (`0.95;1.00` gives 0.000/0.262/0.521/0.775/1.000 against a true S of 0.000/0.156/0.500/0.844/1.000). A straight line scores 0.0682. The error flips sign across the midpoint (+5.3 steps at t=0.25, -3.4 at t=0.75). Splitting cuts the error 12.8x with a worst point of 0.2 steps.

### What vox C7 is

All 2447 v12/v13 charts, every gap between consecutive points inside one run (gaps in 192nds of a measure):

| C7 | gaps | p50 | p90 | p99 | share > 1/32 measure | median \|dpos\| on those |
|---|---|---|---|---|---|---|
| 0 (linear) | 237781 | 48.00 | 128.00 | 336.00 | 95.4% | 0.0000 |
| 2 (Hermite) | 224373 | 3.00 | 3.00 | 4.00 | 0.23% | 0.021 |
| 3 (interp. linear) | 11583 | 3.00 | 3.00 | 4.00 | 0.87% | 0.012 |
| 4 (sine ease out) | 567710 | 3.00 | 3.00 | 4.00 | 0.23% | 0.017 |
| 5 (sine ease in) | 327613 | 3.00 | 3.00 | 4.00 | 0.36% | 0.024 |

The sub-1% of non-zero gaps above 1/32 move the knob a median 0.012 to 0.024, about one of ksh's 51 laser steps (1 step = 0.02). `#TRACK ORIGINAL L`/`R` holds the pre-interpolation nodes, averaging 2.25x fewer points than the matching lane.

Monotonic same-C7 stretches of 8 or more points from 400 charts, normalised and averaged:

| C7 | measured y at t=.25/.50/.75 | ideal | best `<a>;<b>` |
|---|---|---|---|
| 4 (sine ease out) | 0.400 / 0.701 / 0.905 | 0.383 / 0.707 / 0.924 | `0.6;1.0` |
| 5 (sine ease in) | 0.105 / 0.327 / 0.634 | 0.076 / 0.293 / 0.617 | `0.4;0.0` |

Residual rms is about 0.005, a quarter of a laser step. Half an S (`0.37;0.00`) and a sine ease (`0.41;0.00`) differ by rms 0.0133, so the inflection split matters far more than the easing family. Types 2 and 3 average to near-linear (0.273/0.511/0.747 and 0.280/0.540/0.765).

### The fit

Against all 8255 charts (data/music plus the update folder), scored against the polyline the arcade draws: 1,492,920 points become 1,334,733 (-10.6%) with 49,116 curve options, and rms error drops from 0.423 to 0.185 laser steps. Over MXM/INF only it's -29% points and 0.518 to 0.183 steps. What remains above a step of error is the minimum-gap squeeze both versions share.

`_curve_or_none` fits on the two-decimal values the option line can carry, in real position units. The density cut (`CURVE_LEG_FRAC`) is read off the C7 table: generated points sit at a median gap of 3/192 and p99 of 4/192, type-0 gaps at a quarter note with 95.4% wider than 1/32, so a 32nd note admits nearly all the former and none of the latter.

`2061_stylus_humer_5m` measure 7 is a real authored 9-point staircase that v2 reproduces exactly. A corner or reversal fails the fit at any amplitude down to about one laser step. Below that the shape is flattened, since half a step of error is finer than ksh's 51 positions. v1's `RDP_TOL` is five times tighter and keeps some of it. At 32nd-note spacing neither version survives; that's ksh's own slam cutoff.

## Bugs found and fixed

All verified on the full reference aggregate (649 charts) and found on charts outside the original 30-chart matched set.

1. `shared/vox_parser.py` dropped `#END POSITION`'s data (an `#END` prefix check also matched that tag).
2. A fast curve tail could land its last point exactly on ksh's slam cutoff, drawing an unintended slam.
3. A same-tick slam on a run boundary lost its endpoint and drew a diagonal. The fix was half right; see 11.
4. The min-gap pass could keep a near-extremum instead of the true peak, shifting turning points early. Took three attempts to get right without regressing the aggregate.
5. A slam's end landed on the next free tick, a hairline next to hand charts. Now `SLAM_GAP_FRAC`. A first version could run a slam past the next run's start and swallow the gap `LaserLane.anchors()` needs (`gryphone/mxm` laser runs 204 to 155). Now checks the next run's true start.
6. v2: a curve fitted over sparse linear points invented curvature (`2010_xroinrmx_xi_5m` tick 6708, 24 steps off). 261 curves across the MXM charts did this (2.3%). The metric couldn't see it because it scored at the vox points too. Fixed by `CURVE_LEG_FRAC` and by scoring against the polyline: 261 cases down to 13, worst 24 to 4.2 steps. The 13 left are staircases too fine for ksh, where the curve still beats the straight line (4.16 steps against 5.94).
7. v2: the inflection rule fired on stretches too sparse for a curve (`2242_hihouwaineat_shu_5m` tick 6504, 14 steps off, now 0.38 against v1's 4.76). Gated on the same density test.
8. v2: a split too near an end was dropped, taking a legal split with it (`2226_gryphone_etia` tick 12408, 14 steps off). Now moved instead.
9. v2: turning points were thinned left to right, so room went to the wrong reversal (`0653_konransyojo_kameria_4i` measure 56, a trough at 0.26 and a spike to 0.75 nine ticks apart with a twelve-tick minimum gap; 24.9 to 4.9 steps). Now picks the reversal furthest from the chord (`_most_deviant`).
10. The minimum spacing was a fraction of the measure, not a note value. `min_gap = measure_length // 24` is a 24th note in 4/4, but a 3/4 measure got 6 ticks (the slam cutoff itself) and `0536_chase_in_the_shine_penoreri_3e`'s 41-beat measure got 82, which flattened features 12 ticks apart (50 steps off, the worst in the corpus for both versions; now 0). Now `whole_note // min_gap_frac`. Reference aggregate: buttons and laser runs unchanged, laser points 24.25 to 23.23 mean error, exact matches 10.3% to 10.8%, 48 charts better and 27 worse, net 661 points. All 27 worse are shorter-than-4/4 charts (`heavens_rain` and `military_r04d` are 3/4, `oz` goes down to 1/32) where the gap got stricter (6 ticks to 8 in 3/4). The best single gain was `windy_fairy/mxm` (105 points of error to 1). Whole corpus: v1 rms 0.4231 to 0.4189 and worst 50.00 to 44.44, v2 rms 0.1853 to 0.1533 and worst 50.00 to 33.33; v2 stretches over one step 577 to 558; v1 points 1,492,920 to 1,490,571. The worst now is `0798_uroboros_mizonokuchi_3e` at 33 steps with `min_gap` 8 and four raw points, a real format limit.
11. Two sections handing off on one tick came out as a phantom slam. Ending a section costs a whole `-` row, so two sections need two ticks apart, and bug 3's fix left one. KSM spliced them into one laser whose value change on adjacent rows reads as a slam (`2397_ultracharge_yutaimai_5m` measures 53 to 54). Two neighbouring shapes had no fix: a vox-native one-tick gap, and a slam landing pushed past the next run's start, which made `run_at` drop the earlier run (`0223_syonenha_sorawo_tadoru_toromaru_3e` lost a two-point slam run). Fixed by `_separate_runs`, a backward sweep so a shift doesn't just move the collision upstream. A jump that rounds to the same ksh step only needs one tick, since separating those would invent a release and regrab (40 of 130 same-tick handoffs, 9 of 11 in `spear_of_justice/mxm`). Over 8105 charts: 66 phantom slams, 114 overlapped or shared boundaries and 25 merged vox-native gaps go to zero, and laser points shadowed by a later run drop 340 to 129. Runs and points are unchanged. Reference aggregate: buttons unchanged, laser-run exact matches 94.0% to 94.5%, mean error 0.30 to 0.31 (4 charts better, 7 worse, because hand charters merge more than vox does), laser points 23.23 to 23.29. Direct check: 27 of 28 visible jumps have a `-` break in the hand chart; charters end the first section earlier, on the phrase. Open: the remaining 129 are chained same-tick stacks of 3 or more points, which come out with non-monotonic ticks in 322 runs.
12. The beat column of a `measure,beat,cell` timing was read as a quarter note, so events past the first beat of a non-`/4` measure landed late (`2152_nemsysarena_tonarinoniwa_3e` measure 54, 15/16: beat 12 of the following 12/16 measure at offset 528 in a 144-cell measure). `vox_format.md` had it right ("Number of cells per beat = x / beat value"). Across 8254 charts and 7,492,359 timing rows, no `beat` is at or above the numerator and no `cell` is at or above `res*4/den`; under the old reading 47,156 rows fell outside their own measure. 501 charts have a non-`/4` signature and 416 of them moved. Reference aggregate: BT chip error 1.33 to 0.84 (exact 92.6% to 95.1%, 18 better and 0 worse), BT hold 0.18 to 0.12 (11/0), FX chip 0.44 to 0.34 (10/0), FX hold 0.33 to 0.30 (9/0), laser runs 0.31 to 0.15 (16/0), laser points 23.29 to 21.19 (11/4). Six charts now match exactly: `spear_of_justice/mxm` BT chips 469 to 505, `extridia/mxm` 579 to 620, `heartache/mxm` 340 to 374, with laser runs 96 to 83, 74 to 69, 69 to 56. `bars` doesn't move (44.5% to 44.7% exact): a chart whose last real event moves earlier loses an outro measure to the `last_tick` trim. `render_chart.py` had the same bug; see `audio_engine.md` §5.3b.

Items 1 to 5 were found against charts outside the matched set and verified against the full aggregate (649 charts, up from the original 30). Items 6 to 9 were found by sweeping all 8255 charts, never the matched set.

## Moved from the spec

* The spec used to say v2 writes "about 10% fewer laser points" over the whole corpus and cuts the error against the arcade's polyline by more than half. The Checking section above says about 30% fewer against the v1 references. The two figures come from different comparisons and haven't been reconciled.
* Item 12 (beat column): about 500 charts have a non-`/4` measure (501 of 8254).
