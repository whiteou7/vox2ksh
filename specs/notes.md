# The notes element — `.vox` buttons/lasers → `.ksh` chart body

Implementation: [`../scripts/notes/`](../scripts/notes/). Formats: [`vox_format.md`](vox_format.md), [`ksh_format.md`](ksh_format.md).

## Scope

BT/FX/laser notes, plus just enough BPM/time-signature to build the grid. Out of scope: all metadata (placeholders), every sound-fx parameter (already in the audio track), roll/swing (camera element - see `camera.md`), `#TRACK AUTO TAB`.

## Buttons

Direct grid mapping - vox ticks are always a whole multiple of whatever line count ksh uses, so this is exact. Each measure's line count is picked independently via gcd over that measure's real events. BT: `1` chip / `2` hold. FX: `2` chip / `1` hold (swapped vs BT per `ksh_format.md`). Chart length is the last real event, not vox's `#END POSITION` (which is the arcade chart's official end and often runs measures past the last note into silence).

## Lasers

Vox's laser tracks are pre-sampled curves (as fine as 1/64 of a measure), and ksh only has discrete points joined by `:` or a slam - so every curve gets decimated (Douglas-Peucker + a minimum-spacing pass at 1/24 of a measure) before it's written. Three problems, all in `laser.py`:

* **Width** - vox's normal/wide flag maps straight onto `laserrange_l`/`laserrange_r=2x`.
* **Continuity** - decimation must never leave two non-slam points closer than 1/24 of a measure, or ksh's engine reads the movement as an unintended slam (its own cutoff is 1/32).
* **Genuine same-tick slams** - kept exactly, including when the slam sits on a run *boundary* rather than inside one run's points. By default the end lands `SLAM_GAP_FRAC` (1/64 of the local measure) after the start, matching hand-charted slam width, instead of the bare next free tick (`slam_gap_frac=0`, CLI `--no-slam-gap`, GUI "Standard slam gap" checkbox); a dense enough chain (8 slams to a beat is the densest seen) can leave less than that much room, in which case the end just backs off to one tick before the collision.
* **The unrepresentable 32nd slam** - accepted as a real format limit when unavoidable, flagged via `Run.tight` rather than silently eaten.

## Crosscheck

`xcheck.py` matches every reference chart it can (30 pairs currently, same name-matching as `audio/masscheck.py`) and compares note/hold/laser-point counts, not text. BT/FX/laser-run counts match almost exactly; laser points land within ~4% mean (curve decimation approximates a shape, it isn't meant to reproduce one charter's exact point choices). See `RDP_TOL`/`min_gap_frac` in `laser.py` for the tuned constants.

## KSH format version 2

Everything [`ksh_format.md`](ksh_format.md) marks "(Not supported in KSM v1.xx)" — nothing else in the spec carries the marker:

* `title_translit`, `artist_translit` — transliterated title/artist (header).
* `chokkakuse` **with a filename value** — the presets (`up`/`down`/`swing`/`mute`) work in v1.xx, filenames don't.
* `scroll_speed` — scroll multiplier, linear graph.
* `rotation_deg` — rotation in degrees, linear graph.
* `scroll_speed_curve`, `rotation_deg_curve`, `zoom_top_curve`, `zoom_bottom_curve`, `zoom_side_curve`, `center_split_curve`, `tilt_curve` — curve interpolation for the matching parameter.
* `laser_l_curve`, `laser_r_curve` — curve interpolation for laser positions.

All ten `*_curve` options share one payload: `"<a>;<b>"`, floats in [0.0, 1.0], applied at the same pulse in the same measure.

### Laser curves (`laser_l_curve`/`laser_r_curve`)

**ksh side.** One option covers one segment — its own laser point to the next. The segment is a quadratic bezier: endpoints are the two laser points, middle control point is `(a, b)` normalised within the segment (`a` time, `b` position). So `a == b` is neutral (control point on the diagonal, `x(s) == y(s)`, segment stays straight), and mirroring in time maps `(a, b)` to `(1-a, 1-b)`. Per `ksh_format.md`, to curve the line laser after a slam the option goes just before the slam. Stated v2 behaviour, **not** verified against a KSM v2 build.

Two distinct limits, easily confused:

* **Scope** — one option, one segment. A multi-point run needs one option per segment. This is what bites a laser that reverses: the reversal forces a point there, ending the option's reach.
* **Geometry** — a parabola's curvature cannot change sign, so **one segment can never make an S**. This bites even a laser that never reverses, since an ease-in-ease-out sweep is monotonic but has an inflection.

So the bezier goes on twice, over the two halves of the sweep. Fitting smoothstep (`t²(3-2t)`, what a Hermite spline with zero end derivatives gives):

| fitted as | best `<a>;<b>` | rms | laser steps |
|---|---|---|---|
| one segment, whole S | degenerate, see below | 0.0652 | 3.3 |
| first half, renormalised | `0.37;0.00` | 0.0051 | 0.25 |
| second half, renormalised | `0.63;1.00` | 0.0051 | 0.25 |

"One segment" = emit only the sweep's two endpoints, one option on the start; the split versions add a laser point at the inflection to hang a second option on.

The unsplit fit is degenerate, not merely inaccurate. Smoothstep is symmetric, so `0.95;1.00` and its mirror `0.05;0.00` tie exactly, and all 92 grid cells within 0.001 of the minimum have `|a - b|` in 0.03-0.08 — the solution band hugs the neutral diagonal, so every candidate is near-straight (`0.95;1.00` gives 0.000/0.262/0.521/0.775/1.000 against a true S of 0.000/0.156/0.500/0.844/1.000). A plain straight line scores 0.0682. **Fitting an unsplit S buys 0.003 rms over emitting no curve at all — 0.15 of a laser step.** The error flips sign across the midpoint (+5.3 steps at t = 0.25, -3.4 at t = 0.75): the parabola can do the ease-in or the ease-out, not both, so it does neither. Splitting drops the error 12.8×, worst point 0.2 steps. Inflection detection is the precondition for curve fitting to be worth doing at all, not a refinement on top of it.

**vox side — C7 carries no shape the points don't already have.** All 2447 v12/v13 charts in `data/music/`, every gap between consecutive points *inside* one run (run boundaries excluded — a gap spanning two runs isn't a segment):

| C7 | gaps | p50 | p90 | p99 | share > 1/32 measure | median \|Δpos\| on those |
|---|---|---|---|---|---|---|
| 0 (linear) | 237781 | 48.00 | 128.00 | 336.00 | 95.4 % | 0.0000 |
| 2 (Hermite) | 224373 | 3.00 | 3.00 | 4.00 | 0.23 % | 0.021 |
| 3 (interp. linear) | 11583 | 3.00 | 3.00 | 4.00 | 0.87 % | 0.012 |
| 4 (sine ease out) | 567710 | 3.00 | 3.00 | 4.00 | 0.23 % | 0.017 |
| 5 (sine ease in) | 327613 | 3.00 | 3.00 | 4.00 | 0.36 % | 0.024 |

Gaps are in 192nds of a measure, comparable across charts with a non-48 `#BEAT RESOLUTION`. Every non-zero type sits at a **median gap of 3/192 = 1/64 of a measure**, p99 4/192; type `0` sits at a quarter note and is 95 % wider than 1/32 — type `0` rows are the real control points, everything else is pre-sampled fill. The sub-1 % of non-zero gaps exceeding 1/32 move the knob by a median 0.012-0.024, about one of ksh's 51 laser steps (1 step = 0.02), so those are near-stationary stretches carrying no shape either. `#TRACK ORIGINAL L`/`R` holds the pre-interpolation nodes, averaging 2.25× fewer points than the matching lane.

So C7 is a **provenance tag on generated points**, not a renderer instruction: joining the points linearly reproduces the authored curve to well under one laser step, which is what `laser.py` already relies on. Reading C7 is neither required nor a shortcut — the shape lives in the points.

**C7 is still useful going the other way**, naming the shape when we re-fit for v2. Monotonic same-C7 stretches of ≥ 8 points from 400 charts, normalised to the unit square and averaged:

| C7 | measured y at t = .25/.50/.75 | ideal | best `<a>;<b>` |
|---|---|---|---|
| 4 (sine ease out) | 0.400 / 0.701 / 0.905 | sin(tπ/2) = 0.383 / 0.707 / 0.924 | `0.6;1.0` |
| 5 (sine ease in) | 0.105 / 0.327 / 0.634 | 1-cos(tπ/2) = 0.076 / 0.293 / 0.617 | `0.4;0.0` |

Exact mirrors under `(1-a, 1-b)`, and they agree from two directions — fitting the analytic sine and taking the median of per-stretch corpus fits both land there. Residual rms ≈ 0.005, a quarter of a laser step, so a quadratic approximates a sine ease *below ksh's own positional quantisation*. Half an S (`0.37;0.00`) and a sine ease (`0.41;0.00`) differ by rms 0.0133, about ⅔ of a step, so the inflection split matters far more than which easing family is picked. Types `2` and `3` average to near-linear (0.273/0.511/0.747 and 0.280/0.540/0.765) because instances differ — type `2`'s Hermite derivatives aren't in the vox file at all — so both need per-segment fitting rather than a per-type constant.

**The conversion is a re-fit, not a translation:** decimate as now, split each run at direction changes *and* at inflections, then fit `(a, b)` per monotonic segment against the vox points it spans. Open: whether to emit a curve only where the fit beats linear by enough to earn the line, and how splitting interacts with the existing slam and minimum-spacing passes in `laser.py`.

## Bugs found and fixed

1. `shared/vox.py` dropped `#END POSITION`'s data (an `#END`-prefix check also matched that opening tag).
2. A fast curve tail could land its last kept point exactly on ksh's slam cutoff, rendering an unintended slam.
3. A same-tick slam landing on a run *boundary* (rather than inside one run) lost its true endpoint entirely, drawing a diagonal instead of a vertical drop.
4. The min-gap pass could keep a near-extremum instead of the true peak/trough, shifting turning points a few ticks early. Took three attempts to get right without regressing the 30-chart aggregate - see git history / `laser.py` comments for the two broken interim versions if this needs revisiting.
5. A genuine same-tick slam's end used to land on the bare next free tick - technically valid but a near-invisible hairline next to a hand-charted slam, and it forced that measure's grid down to near-native resolution just to place one point. Switched the default to a fixed 1/64-of-a-measure gap (`SLAM_GAP_FRAC`); the first version of this only looked ahead within the same run for a collision, so a run whose *own last point* was a slam could land its end on or past the *next run's* start tick, silently swallowing the one-tick gap `LaserLane.anchors()` needs to keep two runs visually distinct - found via the 649-chart aggregate (`gryphone/mxm.ksh`'s laser-run count went 204→155). Fixed by also checking the next run's true start tick, not just the next point in the current run.

All five found against charts outside the matched reference set; all verified against the full aggregate (649 charts as of this writing, up from the original 30 - see `reverse-engineering-corpus-scoring` in project memory) before being called fixed.
