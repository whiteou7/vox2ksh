#!/usr/bin/env python3
"""
.vox laser track -> discrete .ksh laser points.

The three problems named in HANDOFF.md 3.1:

1. Width. Vox's C5 (1 normal / 2 wide) maps straight onto ksh's
   `laserrange_l`/`laserrange_r` = "2x", restated before every wide run (the
   reference conversions never emit "=1x" - width apparently reverts to
   normal on its own once a run ends, so a reset is never written).

2. Continuity. A vox laser track already comes pre-interpolated (TRACK1/8
   hold the *sampled* curve, not just its control points - see
   specs/vox_format.md's note on `#TRACK ORIGINAL L/R`), and real charts
   sample curves as finely as every 3 ticks (1/64 of a 4/4 measure at the
   default 48-cell resolution). Ksh has no native curve segment: it is only
   ever a grid of discrete points joined by ':' (straight line) or nothing
   (slam). Reproducing every vox sample point would put two distinct laser
   values 1/64 of a measure apart, which is *shorter* than ksh's own slam
   cutoff (1/32) - turning an intended smooth sweep into a string of
   unintended slams.

   So every curve is decimated before it is written: points are dropped by
   Douglas-Peucker simplification, then a second pass enforces a minimum
   spacing of 1/24 of a measure between whatever points survive - the
   practical threshold this project has settled on for "still reads as a
   continuous laser" (see HANDOFF.md 3.1; ksh's own doc says 1/32, but that
   is the point at which the *engine* calls something a slam, not a safe
   authoring margin - 1/24 is the working number here). The run's true start
   and end are always kept even if that leaves a short final segment - see
   (3).

3. No 1/32-or-shorter non-slam segment is representable. A vox chart can
   have two curve points genuinely closer than that which were *not* meant
   to be a slam. Decimation throws away closely spaced points in the common
   case (they are almost always near-collinear with their neighbours - that
   is *why* they are close together), but nothing stops a chart from having
   a real, sharp bend inside a sub-1/24 gap. This converter accepts the
   resulting shape error there; no ksh construct does better. `Run.tight`
   flags runs where the minimum-gap rule had to be broken, so the caller can
   report it instead of silently eating it.

   This is genuinely rare, not the common case - `_enforce_min_gap` backs
   off the *previous* kept point first (see its docstring) whenever that
   alone clears the violation, which it does for an ordinary fast curve
   tail (e.g. a sine ease-in landing its last sample inside 1/32 of the
   measure - a real bug caught against 2393_alive_dadadaizu, not this
   limitation). `Run.tight` now only fires when even the run's true start
   is too close to its true end - across all 30 charts xcheck.py currently
   matches, that's zero runs.

A true vox slam - two points at the identical tick - is different from all of the above: it is not a curve to approximate, it is a real instantaneous jump, and both values must survive untouched. Ksh has no "same row, two values" - the second point needs a tick of its own. By default it lands a 32nd note after the first (`SLAM_GAP_FRAC`, a divisor of the whole note - so 1/8 of a beat, 6 ticks at the default 48-cell resolution), which is what the reference hand charts use: 1/8 of a beat is the most common slam gap in every time signature they contain. Not just the very next free tick, which technically works too but renders as a near-invisible hairline next to a normal hand-charted slam and forces that measure's grid down to near-native resolution just to place one point (see convert.py's resolution picker).

The gap is a note value, never a fraction of the *local measure*. Those agree in 4/4 and diverge everywhere else, and the measure-relative version is wrong in both directions: in a measure longer than 4/4 it overshoots ksh's slam-recognition cutoff, which is beat-relative, and the "slam" then draws as an ordinary diagonal laser (found against 2293_leflector_niwashi_5m - its 7/4 measures got 10-tick gaps where its 4/4 measures got 6 - user-reported); in a measure shorter than 4/4 it undershoots into hairline territory again.

A dense enough slam chain - 8 slams to a beat, i.e. 32nd-note spacing, is the densest this project has seen - can leave less than a 32nd note between one slam's start and the next, in which case the standard gap would land the first slam's end on or past the second slam's start; `_slam_landing_tick` doesn't do anything clever about that, it just backs the end off to one tick before the collision. The visual difference between a slam landing a 32nd note out and one tick out isn't perceptible, and one tick of separation is all ksh actually needs to parse the two points as distinct rows. `build_runs(..., slam_gap_frac=0)` - wired to the CLI's `--no-slam-gap` and the GUI's "Standard slam gap" checkbox - turns this off and goes back to the bare next-free-tick placement.

Because the landing point sits `SLAM_GAP_FRAC` later than the raw shared tick, the curve segment that *starts* at that landing has to be decimated from where the landing actually lands, not from the raw tick - otherwise the first surviving point of a sweep coming straight out of a slam sits a slam-gap too close, inside ksh's 1/32 cutoff, and renders as a second slam right on the heels of the real one. See `_enforce_min_gap`'s `lead`.

The same "same row, two values" problem can also land on a *run boundary*
instead of inside one run's own point list: vox flags one run's true end
and the next run's true start at the identical tick (node_type 2 then 1,
same tick) rather than folding it into one run's own point sequence -
common in zigzag/chain laser patterns. `build_runs`'s tie-breaking in
`LaserLane.run_at` (convert.py) always resolves that shared tick to
whichever run *starts* there, so without correction the earlier run's true
endpoint never gets a row at all - the output draws a straight line from
that run's second-to-last point clear through to the next run's landing
value, a multi-tick diagonal standing in for what should be a vertical hold
followed by an instant drop. `build_runs` moves the earlier run's endpoint
one tick earlier so both get a row - found and fixed against
2397_ultracharge_yutaimai (user-reported); occurs zero times in the 30
reference charts xcheck.py currently matches, so it went uncaught there.

ksh format version 2 changes what "approximate the curve" even means, and `build_runs(curves=True)` takes that path. `laser_l_curve`/`laser_r_curve` give one segment - one laser point to the next - a quadratic bezier: the two laser points are the endpoints and the option's `"<a>;<b>"` payload is the control point normalised inside that segment's own box, `a` across time and `b` across position. `a == b` puts the control point on the diagonal and the segment stays straight; mirroring in time maps `(a, b)` to `(1-a, 1-b)`. Every slam-free stretch then goes through decimate_segment_curved() instead of decimate_segment(), which is a re-fit and not a decimation: it keeps the stretch's own turning points and inflections rather than every point a polyline needs to trace the curve, and gives each surviving segment the (a, b) that best reproduces the vox samples it spans. Over the whole 8000-chart corpus that is about 30 % fewer laser points at well under half of v1's shape error.

Two limits decide where a stretch has to be split, and they are easy to confuse. Scope: one option covers one segment, so a laser that reverses forces a point at the reversal and ends that option's reach (_direction_breaks). Geometry: a parabola's curvature cannot change sign, so one segment can never make an S - which bites even a laser that never reverses, since an ease-in-ease-out sweep is monotonic but has an inflection (_inflection_index). Everything else here is version-independent and shared: slam placement, width, the run-boundary fixup and the minimum-gap rule all apply unchanged, because a v2 chart's laser points are ordinary ksh laser points - two of them 1/32 of a measure apart still read as a slam whether an option line sits on them or not.

Nothing in the v2 path reads vox's own curve type (C7). It is a provenance tag on generated points rather than a renderer instruction: joining the points linearly already reproduces the authored curve to well under one laser step, measured across all 2447 v12/v13 charts in specs/notes.md. Re-deriving the shape from the points instead is also what lets the fit follow a stretch whose C7 is 2 (Hermite), whose defining derivatives are not in the vox file at all.
"""

import math

KSH_STEPS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmno"   # 51 steps
N_STEPS = len(KSH_STEPS) - 1   # 50 - the top index

# Douglas-Peucker tolerance, in ksh-step units (0..1 over the full 51 steps).
# Half a step (1/100) is the quantisation floor - a point closer to the
# straight line than that is literally invisible after rounding - but that
# alone simplifies harder than the reference conversions do (crosschecked
# against scripts/shared/reference/ksh via notes/xcheck.py: half a step
# keeps noticeably fewer points than the manual charts on every song tried).
# Swept 0..half-a-step against all 30 charts xcheck.py currently matches
# (every difficulty in every reference folder with a corresponding .vox,
# not just the 5 first tried) and took the total point-count error's
# minimum, a broad, shallow plateau from about 1/500 to 1/475 - 1/500 sits
# in it. Not derived from anything in the format, just the best empirical
# fit; re-sweep (see the sweep in this file's git history, or redo it
# inline) if xcheck.py picks up more reference charts.
RDP_TOL = 1.0 / 500

# Default gap from a genuine same-tick vox slam's start to where its end lands in the ksh output, as a divisor of the whole note - 32 is a 32nd note, i.e. 1/8 of a beat, which is what the reference hand charts use in every time signature. Deliberately not a fraction of the local measure; see the module docstring's "true vox slam" paragraph for why that breaks outside 4/4. `build_runs(slam_gap_frac=0)` disables this and falls back to the old bare next-free-tick placement.
SLAM_GAP_FRAC = 32

# ksh's own slam-recognition cutoff (1/32-or-shorter reads as a slam - see
# the module docstring's point 1) - a fixed engine constant, kept separate
# from SLAM_GAP_FRAC even though they default to the same 32 by coincidence:
# SLAM_GAP_FRAC is this project's tuning knob for how a genuine slam is
# *drawn*, this is what the *engine* treats as the boundary. Used by
# _slam_landing_tick to work out the least backoff that keeps the leg
# *after* a slam landing from itself being misread as a second slam - see
# its docstring.
KSH_SLAM_CUTOFF_FRAC = 32


def pos_to_char(pos):
    pos = 0.0 if pos < 0.0 else (1.0 if pos > 1.0 else pos)
    return KSH_STEPS[int(round(pos * N_STEPS))]


class Run:
    """One continuous laser gesture: a vox node_type==1 start through its
    node_type==2 end, decimated to the points that will actually get a
    character in the .ksh output.

    `points`     [(tick, pos), ...], strictly increasing in tick, always
                 including the run's true start and true end.
    `slam_after` slam_after[i] is True iff points[i] -> points[i+1] is a
                 genuine vox same-tick slam (points[i+1]'s tick has already
                 been bumped to the next free tick so it gets its own line;
                 no ':' goes between a slam pair).
    `width`      1 (normal) or 2 (wide), from the run's first point.
    `tight`      True if decimating this run required breaking the
                 minimum-gap rule to preserve the true start/end - i.e. a
                 real sub-1/24 gap existed that isn't a slam. See (3) above.
    `curves`     ksh v2 only, parallel to `slam_after`: curves[i] is the (a, b) bezier control point drawing points[i] -> points[i+1], or None for a plain straight join. All None in v1 mode (build_runs(curves=False), the default), which is what makes a v1 conversion byte-identical to what this module produced before v2 existed.
    """

    __slots__ = ("points", "slam_after", "width", "tight", "curves")

    def __init__(self, points, slam_after, width, tight, curves=None):
        self.points = points
        self.slam_after = slam_after
        self.width = width
        self.tight = tight
        self.curves = curves if curves is not None else [None] * max(0, len(points) - 1)

    @property
    def start_tick(self):
        return self.points[0][0]

    @property
    def end_tick(self):
        return self.points[-1][0]


def _rdp(pts, tol):
    """Douglas-Peucker on a strictly-tick-increasing (tick, pos) list."""
    if len(pts) <= 2:
        return pts
    t0, v0 = pts[0]
    t1, v1 = pts[-1]
    span = t1 - t0
    worst_d, worst_i = -1.0, -1
    for i in range(1, len(pts) - 1):
        t, v = pts[i]
        f = (t - t0) / span if span else 0.0
        vi = v0 + (v1 - v0) * f
        d = abs(v - vi)
        if d > worst_d:
            worst_d, worst_i = d, i
    if worst_d <= tol:
        return [pts[0], pts[-1]]
    left = _rdp(pts[:worst_i + 1], tol)
    right = _rdp(pts[worst_i:], tol)
    return left[:-1] + right


def _enforce_min_gap(pts, min_gap, lead=0):
    """Greedy left-to-right thinning so no two consecutive kept points are
    closer than `min_gap` ticks - except the run's true end, which is
    always kept regardless. Returns (kept_points, tight).

    `lead` is how many ticks past its own tick `pts[0]` will actually be written at, and is nonzero exactly for a segment that begins at a genuine slam's landing point: build_runs places that point `slam_gap` ticks after the raw shared tick (see SLAM_GAP_FRAC), so spacing the rest of the segment from the raw tick leaves the first surviving curve point `slam_gap` ticks closer to it than the min-gap rule intends. That shortfall lands inside ksh's own 1/32 slam cutoff whenever the curve turns sharply straight out of the slam, and the sweep's first leg then renders as a second slam immediately after the real one - a slam-slam stutter where the chart means slam-then-sweep. Found against 2293_leflector_niwashi_5m tick 4440 (measure 24 beat 1.5, user-reported): the landing sat at 4446 and the next kept point at 4449, 3 ticks later. `lead` is the *nominal* gap; a landing that gets backed off from a ceiling collision only ends up further from the next point, never closer, so reserving the nominal amount is always safe.

    A fast-but-continuous curve tail (e.g. a sine ease-in, slow start then
    sharp finish) can leave the forward pass one point away from the end
    with too little room - a real bug, not the sub-1/24 format limit this
    module otherwise documents: the run's true shape has plenty of room a
    little further back, the forward pass just didn't know that yet. Before
    accepting the violation, walk backward dropping the most recent kept
    points - each one it drops connects the run's end straight back to an
    earlier point instead, which is extra approximation error but avoids
    landing exactly on ksh's slam cutoff for a movement that was never meant
    to be a slam. Only genuinely unavoidable when even the run's own start
    is too close to its end.

    The forward pass keeps *whichever* candidate first clears min_gap from
    the previously kept point, which is not always the best one: a true
    local extremum (a curve's peak or trough) often has several
    RDP-surviving points within min_gap of each other on its way in and
    out, and the first one to clear the gap can land a few ticks short of
    the extremum itself - visibly shifting the turning point early. Fixed
    by a second pass, deliberately bounded to each slot's own dropped
    candidates (never chaining forward past them - an unbounded version of
    this tried first, and either collapsed long monotonic runs to a single
    point or, worse, kept a point for every tiny wiggle in a fast
    oscillation instead of thinning it, depending on which direction the
    bug leaned): for each kept point, if a candidate that was dropped for
    being too close to it is *more extreme* in the same direction the curve
    was already heading, and swapping it in still clears min_gap from both
    neighbours, use it instead. Found and fixed against 2226_gryphone_etia:
    a real trough at a run's tick 3792 was dropped in favour of a
    slightly-higher, slightly-earlier point at 3786, six ticks short of the
    threshold, shifting the visible turning point six ticks early.

    That second pass must not fire when the leg *into* the kept point is
    flat. `rising` was originally `best_v >= prev_v`, which reads a flat
    approach as "rising", so a candidate anywhere above the hold counted as
    "more extreme" and replaced the point - but a kept point with a flat leg
    in is not an extremum, it is the corner where a straight hold ends and a
    curve begins, and moving a corner is never an improvement: it delays the
    turn and drags the hold's end value out along the curve with it. Found
    against 2392_dementafterlegend_cosmograph_5m (format 13) measure 29 beat
    3 to measure 30 beat 1, user-reported: both lanes hold straight for 96
    ticks and then split apart, and the right lane's corner at tick 5568
    (pos 0.375) was replaced by tick 5574 (pos 0.4357) - six ticks late and
    three ksh steps high, so the "straight" section visibly drifted. The
    left lane escaped only by luck of sign: it leaves its hold *downward*,
    so `v >= best_v` failed and no candidate qualified. Requiring a real
    direction (`best_v != prev_v`) fixes the corner case and leaves genuine
    extrema, which by definition have a non-flat leg in, untouched.
    """
    if len(pts) <= 2:
        return pts, (len(pts) == 2 and pts[1][0] - (pts[0][0] + lead) < min_gap)
    out = [pts[0]]
    # `eff` is out[i]'s tick as the output will actually see it - identical to out[i][0] for every point except the first, which `lead` moves. Kept as a parallel list rather than pre-shifting out[0] itself, since out[0]'s own tick is what the caller writes and what the slam-landing placement measures its gap from.
    eff = [pts[0][0] + lead]
    dropped_after = {}   # index into `out` -> [(t, v), ...] dropped right after it
    for t, v in pts[1:-1]:
        if t - eff[-1] >= min_gap:
            out.append((t, v))
            eff.append(t)
        else:
            dropped_after.setdefault(len(out) - 1, []).append((t, v))
    last = pts[-1]
    while len(out) > 1 and last[0] - eff[-1] < min_gap:
        out.pop()
        eff.pop()
    tight = (last[0] - eff[-1]) < min_gap
    out.append(last)
    eff.append(last[0])

    for i in range(1, len(out) - 1):
        cands = dropped_after.get(i, ())
        if not cands:
            continue
        prev_v = out[i - 1][1]
        best_t, best_v = out[i]
        if best_v == prev_v:
            # Flat leg in: out[i] is not an extremum at all, it is the
            # CORNER where a straight hold stops and a curve starts, and
            # the corner's whole job is to be exactly where it is. See the
            # docstring - swapping it forward both delays the turn and
            # drags the hold's end value out along the curve.
            continue
        rising = best_v > prev_v
        for t, v in cands:
            more_extreme = (rising and v >= best_v) or (not rising and v <= best_v)
            if (more_extreme and t - eff[i - 1] >= min_gap
                    and eff[i + 1] - t >= min_gap):
                best_t, best_v = t, v
        out[i] = (best_t, best_v)
        eff[i] = best_t

    return out, tight


def decimate_segment(pts, min_gap, tol=RDP_TOL, lead=0):
    """One slam-free stretch of a run -> (kept_points, tight). `lead` - see _enforce_min_gap."""
    return _enforce_min_gap(_rdp(pts, tol), min_gap, lead)


def _split_into_runs(laser_points):
    """vox LaserPoint stream -> list of point-object lists, one per run.

    A run starts at node_type==1 (or the first point in the track,
    defensively, in case a chart's first laser point is missing its start
    flag) and ends at, inclusive, node_type==2.
    """
    runs, cur = [], []
    for p in laser_points:
        if p.node_type == 1 or not cur:
            if cur:
                runs.append(cur)
            cur = [p]
        else:
            cur.append(p)
        if p.node_type == 2:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return runs


def _split_at_slams(run_pts):
    """One run's points -> list of slam-free (tick, pos) segments, split
    wherever two consecutive points share a tick (a genuine vox slam).
    Segment k's last tick equals segment k+1's first tick by construction.
    """
    segments, seg = [], [(run_pts[0].tick, run_pts[0].pos)]
    for a, b in zip(run_pts, run_pts[1:]):
        if b.tick == a.tick:
            segments.append(seg)
            seg = [(b.tick, b.pos)]
        else:
            seg.append((b.tick, b.pos))
    segments.append(seg)
    return segments


def _bump_to_free_tick(t, used):
    bump = 1
    while (t + bump) in used:
        bump += 1
    used.add(t + bump)
    return t + bump


def _slam_landing_tick(start_t, used, gap, ceiling=None, safe_gap=1, max_backoff=1):
    """Target tick for a genuine same-tick slam's second point: `gap` ticks
    after `start_t` (see SLAM_GAP_FRAC / the module docstring), backed off
    to fit when there isn't room for the full gap.

    `ceiling`, when given, is the tick of whatever point comes next in the
    run (not yet placed itself). Two different constraints both bear on
    where the landing can go:

    - Hard: the landing must not land on or past `ceiling` - two points
      can't share a tick, and a dense slam chain can leave the standard
      gap doing exactly that. This one is non-negotiable; the target backs
      off as far as it takes (`ceiling - 1` at worst), same as always.

    - Soft: the leg *from* the landing *to* `ceiling` should also clear
      ksh's own slam-recognition cutoff (1/32-or-shorter,
      KSH_SLAM_CUTOFF_FRAC - see the module docstring's "true vox slam"
      paragraph) so it doesn't get misread as an unintended second slam
      right on the heels of the real one. `safe_gap` is the least room
      that clears it (one tick past the cutoff). Unlike the hard
      constraint, this one is capped: the landing backs off *at most*
      `max_backoff` ticks from its nominal position trying to satisfy it,
      never more, even when that leaves the trailing leg still inside the
      cutoff. Found and fixed against 2397_ultracharge_yutaimai_5m: at
      measure 17, 12 ticks of total room meant a 1-tick backoff (nominal
      6 -> 5) was already enough to clear the cutoff on the trailing leg,
      no problem. But in the same chart's staircase slam chain at tick
      7592, only 8 ticks of room separated that slam from the run's true
      end - chasing the full `safe_gap` there backed the landing off by 5
      ticks, crushing the slam itself down to a 1-tick hairline next to
      its neighbours (user-reported: "too thin", "should only be deduced
      by 1 tick"). Capping the backoff instead leaves the slam a normal
      5 ticks and accepts that the trailing 3-tick leg may still read as a
      second slam - the same unresolvable squeeze `Run.tight` already
      exists to flag (module docstring point 3): with only 8 ticks between
      a slam and the run's end, no split of that room gives both a
      visible slam *and* a safely-clear tail, so the slam's own width
      wins.
    """
    nominal = start_t + max(1, gap)
    target = nominal
    if ceiling is not None:
        hard_limit = ceiling - 1
        if target > hard_limit:
            target = hard_limit          # mandatory: never collide with ceiling
        soft_limit = ceiling - max(1, safe_gap)
        if target > soft_limit:
            # capped relative to the *nominal* position, not wherever the
            # hard-collision clamp above already left `target` - a dense
            # chain that already forced a bigger-than-max_backoff reduction
            # to avoid an outright collision shouldn't get squeezed further
            # still chasing the softer non-slam-tail goal.
            target = max(soft_limit, nominal - max_backoff, start_t + 1)
            target = min(target, hard_limit)
    while target in used and target > start_t:
        target -= 1
    target = max(target, start_t + 1)
    used.add(target)
    return target


def _bump_to_free_tick_before(t, used, floor):
    """Like _bump_to_free_tick but searches backward, never going past
    `floor` (exclusive) - the tick of whatever point precedes it.
    """
    bump = 1
    while t - bump in used and t - bump > floor:
        bump += 1
    new_t = t - bump
    if new_t <= floor:
        return None      # no free tick between the two points - give up
    used.add(new_t)
    return new_t


# --------------------------------------------------------------------------
# ksh v2: laser curves
# --------------------------------------------------------------------------
#
# Everything from here to build_runs() is inert unless build_runs(curves=True). See the module docstring's "ksh format version 2" section and specs/notes.md.

# How far a written segment may stray from the vox points it spans before it gets split at its worst point, in position units (0..1 across the lane). Half a laser step: the endpoints ksh writes are themselves quantised to 51 steps, so anything finer than half a step in between is below what the format can show. This is the v2 counterpart of RDP_TOL and is deliberately looser - RDP_TOL measures a *straight* chord's error, and v1 has to keep the points it survives close enough together that the polyline still traces the curve, where a v2 segment carries its own shape.
CURVE_FIT_TOL = 0.5 / N_STEPS

# Least a fitted curve has to beat its own straight chord by, in position units, before its option line is worth writing. A quarter of a laser step - below that the two draw the same characters. This and CURVE_FIT_TOL together are specs/notes.md's "emit a curve only where the fit beats linear by enough to earn the line"; _curve_or_none applies them.
CURVE_MIN_GAIN = 0.25 / N_STEPS

# Reversal amplitude below which a turning point isn't one: half a laser step, small enough that the turn and the extremum it turns at round to the same character. Guards _direction_breaks against spending a laser point on the sampling jitter at the top of a slow arc.
CURVE_DEAD_ZONE = 0.5 / N_STEPS

# Longest gap between two consecutive vox points a fitted curve is allowed to span, as a divisor of the whole note - a 32nd note. Wider than that and the stretch gets straight joins between its own points instead, however well a bezier threads them.
#
# This is the difference between recovering a shape and inventing one, and nothing else in this section catches it: a fit is scored against the vox points *at their own ticks*, so where the points are dense (the arcade's own pre-sampled curve fill, 3 ticks apart) "between the points" is nothing and fitting the points fits the shape - but where a charter placed three points 200 ticks apart, almost the whole segment is between points, and a quadratic can thread all three exactly while bowing anywhere it likes in between. Found against 2010_xroinrmx_xi_5m tick 6708: a hold at 0.0 followed by a dead-straight ramp to 1.0, all three points type 0 (linear), written as one `1.00;0.00` curve that passed through every point and bowed 24 laser steps - half the lane - away from the ramp. 261 curves across the MXM charts did this, 2.3 % of all of them.
#
# The cut comes from specs/notes.md's own corpus table rather than being picked: generated points sit at a median gap of 3/192 of a measure and a p99 of 4/192, while type-0 (linear) gaps sit at a quarter note with 95.4 % of them wider than 1/32. A 32nd note admits essentially all of the former and excludes essentially all of the latter. The sub-1 % of generated gaps that do exceed it move the knob by a median 0.012-0.024, about one laser step, so declining to curve those costs nothing either. Expressed as a note value, never a fraction of the local measure - see the module docstring's "true vox slam" paragraph for what that mistake does outside 4/4.
CURVE_LEG_FRAC = 32


def _bezier_s(x, a):
    """The bezier's own parameter at normalised time `x`: solves x = s**2 + 2a*s(1-s) for s in [0, 1].

    Both coordinates of the quadratic bezier through (0,0) and (1,1) with control point (a, b) have this same form - x from a, y from b - which is why a == b is the neutral, perfectly straight control point. x(s) is monotonic for every a in [0, 1] (x'(s) is linear in s and non-negative at both ends), so exactly one root lies in range and it is always the '+' one.
    """
    d = 1.0 - 2.0 * a
    if -1e-12 < d < 1e-12:
        return x                      # a == 0.5 -> x(s) == s
    disc = a * a + d * x
    return (math.sqrt(disc if disc > 0.0 else 0.0) - a) / d


def _score_a(a, xs, ys, scale):
    """One candidate `a` -> (a, b, rms, maxerr), with the matching `b` solved rather than searched.

    y(s) = s**2 + 2b*s(1-s) is *linear* in b once s is known, and s comes from x through `a` alone - so the least-squares b for a given a is a one-line normal equation instead of a second search dimension. b is rounded to what the option line can actually carry (see convert.py's _fmt_curve) before it is scored, so the reported error is the error of the string that gets written, not of an unwritable ideal. Errors come back in real position units (`scale` is the segment's own height): a shallow segment's normalised error means less on screen than a tall one's, and every threshold in this section is a number of laser steps.
    """
    ss = [_bezier_s(x, a) for x in xs]
    num = den = 0.0
    for s, y in zip(ss, ys):
        w = 2.0 * s * (1.0 - s)
        num += w * (y - s * s)
        den += w * w
    b = a if den <= 1e-12 else num / den
    b = round(min(1.0, max(0.0, b)), 2)
    total = worst = 0.0
    for s, y in zip(ss, ys):
        e = abs(y - (s * s + 2.0 * b * s * (1.0 - s))) * scale
        total += e * e
        if e > worst:
            worst = e
    return (round(a, 2), b, (total / len(ys)) ** 0.5, worst)


def _fit_quadratic(pts):
    """One monotonic, single-curvature stretch -> its best (a, b, rms, maxerr), or None where no curve can say anything (a zero-length or perfectly flat span, or nothing between the endpoints to fit).

    A coarse 1/20 sweep over `a`, then a 1/100 refinement around the winner. The objective is smooth in `a`, and both stages land on values the two-decimal option line carries exactly.
    """
    t0, v0 = pts[0]
    t1, v1 = pts[-1]
    dt, dv = t1 - t0, v1 - v0
    if dt <= 0 or dv == 0.0 or len(pts) < 3:
        return None
    xs = [(t - t0) / dt for (t, _v) in pts[1:-1]]
    ys = [(v - v0) / dv for (_t, v) in pts[1:-1]]
    scale = abs(dv)
    best = None
    for i in range(21):
        cand = _score_a(i / 20.0, xs, ys, scale)
        if best is None or cand[2] < best[2]:
            best = cand
    centre = int(round(best[0] * 100))
    for i in range(max(0, centre - 5), min(100, centre + 5) + 1):
        cand = _score_a(i / 100.0, xs, ys, scale)
        if cand[2] < best[2]:
            best = cand
    return best


def _line_error(pts):
    """A stretch's straight chord -> (rms, maxerr) against its own interior points, in position units. The baseline every fitted curve has to beat."""
    t0, v0 = pts[0]
    t1, v1 = pts[-1]
    dt = t1 - t0
    if dt <= 0 or len(pts) < 3:
        return 0.0, 0.0
    total = worst = 0.0
    for (t, v) in pts[1:-1]:
        e = abs(v - (v0 + (v1 - v0) * (t - t0) / dt))
        total += e * e
        if e > worst:
            worst = e
    return (total / (len(pts) - 2)) ** 0.5, worst


def _inflection_index(pts, dev):
    """Where a stretch's deviation from its own chord changes sign, or None if it only ever bulges one way.

    A parabola's curvature cannot change sign, so one option can never make an S (specs/notes.md) - an S has to be split, and its inflection is exactly where the deviation from the chord crosses zero. That crossing is cheaper and far steadier on sampled data than a second difference. A lobe shallower than `dev` on either side isn't an S worth a laser point, it's quantisation.
    """
    t0, v0 = pts[0]
    t1, v1 = pts[-1]
    dt = t1 - t0
    if dt <= 0 or len(pts) < 4:
        return None
    res = [v - (v0 + (v1 - v0) * (t - t0) / dt) for (t, v) in pts]
    hi, lo = max(res), min(res)
    if hi < dev or -lo < dev:
        return None
    i, j = sorted((res.index(hi), res.index(lo)))
    cross = min(range(i, j + 1), key=lambda k: abs(res[k]))
    return cross if 0 < cross < len(pts) - 1 else None


def _most_deviant(pts, idxs):
    """Whichever of `idxs` sits furthest from the chord through pts[0] and pts[-1], or None if `idxs` is empty.

    This is what settles which turning point a stretch too fast to hold them all spends its one available laser point on, and it has to be deviation rather than anything local: two reversals a few ticks apart routinely have the *same* depth against their own neighbours, and picking the earlier one then quietly deletes the deeper excursion (0653_konransyojo_kameria_4i measure 56 - a trough at 0.26 and a spike to 0.75 nine ticks apart, min gap twelve, where keeping the trough left the spike undrawable and keeping the spike left the trough recoverable a few ticks earlier).
    """
    t0, v0 = pts[0]
    t1, v1 = pts[-1]
    dt = t1 - t0
    best_i, best_d = None, -1.0
    for i in idxs:
        t, v = pts[i]
        d = abs(v - (v0 + (v1 - v0) * ((t - t0) / dt if dt else 0.0)))
        if d > best_d:
            best_i, best_d = i, d
    return best_i


def _worst_index(pts, fit):
    """Interior index furthest from whatever the stretch is currently drawn as - `fit`'s curve, or the straight chord when `fit` is None. Where splitting buys the most."""
    t0, v0 = pts[0]
    t1, v1 = pts[-1]
    dt, dv = t1 - t0, v1 - v0
    if dt <= 0 or len(pts) < 3:
        return None
    a, b = (fit[0], fit[1]) if fit else (None, None)
    worst_e, worst_i = -1.0, None
    for k in range(1, len(pts) - 1):
        t, v = pts[k]
        x = (t - t0) / dt
        if a is None:
            pred = v0 + dv * x
        else:
            s = _bezier_s(x, a)
            pred = v0 + dv * (s * s + 2.0 * b * s * (1.0 - s))
        e = abs(v - pred)
        if e > worst_e:
            worst_e, worst_i = e, k
    return worst_i


def _curve_or_none(fit, lin_max):
    """The (a, b) a segment should write, or None to leave it a plain ':' join.

    Two ways a curve fails to earn its option line: the straight chord is already inside CURVE_FIT_TOL (the two render identically once ksh quantises to 51 steps), or the fit beats the chord by less than CURVE_MIN_GAIN. `a == b` is the neutral control point - an option that says "straight" - so it never earns one either.
    """
    if fit is None:
        return None
    a, b, _rms, fit_max = fit
    if a == b or lin_max <= CURVE_FIT_TOL or lin_max - fit_max < CURVE_MIN_GAIN:
        return None
    return (a, b)


def _direction_breaks(pts, dead):
    """Indices of a stretch's turning points - every tick where the laser reverses.

    A reversal is a hard segment boundary for the same reason an inflection is: the bezier runs (0,0) to (1,1) inside its own normalised box, so one option can only ever describe a monotonic move. `dead` ignores a reversal that never gets further than half a laser step from the extremum it turned at - it renders as the same character, and splitting there would spend a laser point on nothing. The break is recorded at the extremum itself, not at the point where the retreat finally cleared `dead`, so a slow arc's peak still lands on its true peak - the same thing _enforce_min_gap's second pass exists to protect on the v1 side.
    """
    breaks = []
    ext, direction = 0, 0
    for i in range(1, len(pts)):
        v, ev = pts[i][1], pts[ext][1]
        if direction == 0:
            if abs(v - ev) > dead:
                direction = 1 if v > ev else -1
                ext = i
        elif (v - ev) * direction > 0:
            ext = i                          # further in the direction we were already going
        elif (ev - v) * direction > dead:
            breaks.append(ext)
            direction = -direction
            ext = i
    return breaks


def _split_window(pts, lo, hi, min_gap, lead):
    """The inclusive index range a split of pts[lo..hi] may land on without leaving two points closer than `min_gap`. Empty (first > last) when the whole stretch has no room for a third point.

    This is where v1's continuity rule (module docstring point 2) enters the v2 path: a v2 chart's laser points are ordinary ksh laser points and the engine reads two of them 1/32 of a measure apart as a slam whether an option line sits on them or not. `lead` - see _enforce_min_gap.
    """
    first, last = lo + 1, hi - 1
    while first <= last and pts[first][0] - (pts[lo][0] + lead) < min_gap:
        first += 1
    while last >= first and pts[hi][0] - pts[last][0] < min_gap:
        last -= 1
    return first, last


def _fit_stretch(pts, lo, hi, min_gap, tol, lead=0, max_leg=None):
    """pts[lo..hi] -> ([kept indices after lo, ending at hi], [curve-or-None, one per resulting segment]).

    Adaptive subdivision, and the only thing that chooses points in the v2 path. A straight join is tried first, then one fitted curve, and only if that still misses by more than `tol` does the stretch get a point in the middle and try again on each half. Where that point goes, in falling priority:

    1. A turning point, if the minimum-gap window has room for one. One option covers one monotonic move, so a reversal cannot be inside a segment at all - and where several compete for one slot, the one furthest from the stretch's own chord wins (see _most_deviant).
    2. Otherwise, on a stretch with no reversal in it, the inflection: specs/notes.md measures an unsplit S as *degenerate* rather than merely inaccurate - every near-optimal (a, b) sits against the neutral diagonal, so the fit buys 0.15 of a laser step over emitting nothing at all. The reversal check has to come first for this to mean anything, since the chord-crossing an inflection is read from is equally happy to fire on a zigzag.
    3. Otherwise the worst-fitting point: a single-curvature stretch that misses is just under-resolved, and resolving it there is what fixes it.

    Whichever wins is *moved* to the nearest index the minimum-gap rule allows rather than abandoned when it lands too near an end. Giving up there was a real bug: a dip bottoming out 6 ticks into a 72-tick stretch put the inflection inside the gap, and dropping the split with it also dropped the perfectly legal one at the stretch's other feature (2226_gryphone_etia tick 12408 - the laser returned to 1.0 and held, and the whole flat top got swallowed by one curve, 14 laser steps out at its worst).
    """
    sub = pts[lo:hi + 1]
    _lin_rms, lin_max = _line_error(sub)
    if lin_max <= tol:
        return [hi], [None]                  # already straight enough to just join
    # A curve is only offered where the points are dense enough to vouch for the shape between them - see CURVE_LEG_FRAC. Where they aren't, `fit` stays None all the way through: the splitter falls back to the chord (which is what the arcade draws between authored points anyway) and every segment comes out a straight join.
    dense = max_leg is None or all(b[0] - a[0] <= max_leg for a, b in zip(sub, sub[1:]))
    fit = _fit_quadratic(sub) if dense else None
    if fit is not None and fit[3] <= tol:
        return [hi], [_curve_or_none(fit, lin_max)]

    first, last = _split_window(pts, lo, hi, min_gap, lead)
    split = None
    if first <= last:
        breaks = _direction_breaks(sub, CURVE_DEAD_ZONE)
        want = _most_deviant(sub, [i for i in breaks if first - lo <= i <= last - lo])
        if want is None and not breaks and dense:
            # The inflection rule exists to serve curve fitting - it is where one parabola stops being able to follow the shape. On a stretch too sparse to fit a curve over at all there is no parabola and no inflection to find, and the chord-crossing it reads instead lands near the chord's own midpoint, which on a hold-then-ramp is nowhere near the corner. Found against 2242_hihouwaineat_shu_5m tick 6504: a 24-tick hold at 0.0 into a fast rise, where splitting at the "inflection" dropped the corner at 6528 and drew straight through it, 14 laser steps out. Falling through to the chord's worst point puts the split on the corner, which is what v1 keeps there too.
            want = _inflection_index(sub, tol)
        if want is None:
            want = _worst_index(sub, fit)
        if want is not None:
            split = min(max(lo + want, first), last)
    if split is not None:
        li, lc = _fit_stretch(pts, lo, split, min_gap, tol, lead, max_leg)
        ri, rc = _fit_stretch(pts, split, hi, min_gap, tol, 0, max_leg)
        return li + ri, lc + rc
    # No room to split: write the best single segment available and accept the error - the same unrepresentable-shape squeeze `Run.tight` flags on the v1 side, reached from the other direction.
    return [hi], [_curve_or_none(fit, lin_max)]


def decimate_segment_curved(pts, min_gap, tol=CURVE_FIT_TOL, lead=0, max_leg=None):
    """One slam-free stretch of a run -> (kept_points, curves, tight). The ksh v2 counterpart of decimate_segment().

    Not a decimation of v1's output but a re-fit of the vox points, per specs/notes.md: _fit_stretch keeps only the points a bezier can't say for itself - turning points, inflections, and wherever one segment still missed by more than `tol` - and `curves[i]` is the (a, b) drawing kept[i] -> kept[i+1], or None for a straight join. The run's true start and end are always kept, and `tight` means the same thing it does in v1: the two are closer than `min_gap` and nothing could go between them. `lead` - see _enforce_min_gap.

    `max_leg` - see CURVE_LEG_FRAC. build_runs passes the exact note value; the fallback below is its 4/4 equivalent, for a caller with only `min_gap` to hand (min_gap is 1/24 of the measure, max_leg 1/32 of it).
    """
    if max_leg is None:
        max_leg = max(1, min_gap * 24 // 32)
    if len(pts) <= 2:
        tight = len(pts) == 2 and pts[1][0] - (pts[0][0] + lead) < min_gap
        return list(pts), [None] * max(0, len(pts) - 1), tight
    idx, curves = _fit_stretch(pts, 0, len(pts) - 1, min_gap, tol, lead, max_leg)
    tight = pts[-1][0] - (pts[0][0] + lead) < min_gap
    return [pts[0]] + [pts[i] for i in idx], curves, tight


def build_runs(laser_points, tl, min_gap_frac=24, slam_gap_frac=SLAM_GAP_FRAC, curves=False):
    """vox LaserPoint stream (one lane, already tick-sorted) -> [Run, ...].

    `min_gap_frac`: minimum point spacing enforced during decimation, as a
    fraction of the *local* measure length (1/24 by default - see the
    module docstring). Never applied across a genuine same-tick slam.

    `curves`: ksh v2 mode. Each slam-free stretch is re-fitted by decimate_segment_curved() instead of decimated by decimate_segment(), and every Run comes back with a `curves` entry per segment for convert.py to write as `laser_l_curve`/`laser_r_curve`. Off by default: v1 has no such option line, so the points themselves have to carry the shape. Only the point-choosing step changes - slam handling, width, the run-boundary fixup and the minimum-gap rule are shared, since a v2 chart's laser points are ordinary ksh laser points that the engine reads by the same rules.

    `slam_gap_frac`: a genuine same-tick slam's start-to-end gap, as a note value - a whole note over `slam_gap_frac`, i.e. a 32nd note by default (see SLAM_GAP_FRAC and the module docstring's "true vox slam" paragraph). Deliberately *not* a fraction of the local measure: ksh's slam cutoff is beat-relative, so in any measure longer than 4/4 a measure-relative gap overshoots it and the slam draws as a plain diagonal laser instead (found against 2293_leflector_niwashi_5m, whose 7/4 measures got 10-tick gaps against 4/4's 6 - user-reported). The reference hand charts settle it: 1/8 of a beat is the most common slam gap in every time signature they use - 4/4, 3/4, 5/4, 6/8, 7/4, 8/4, 11/4 - never a constant slice of the measure. 0 (or any other falsy value) instead places the slam's end on the very next free tick, the older, thinner behaviour.
    """
    # A whole note in ticks: tl.res is cells per quarter note, so this is what `slam_gap_frac` divides, independent of the local time signature.
    whole_note = 4 * tl.res
    used_ticks = set()
    out = []
    run_groups = [g for g in _split_into_runs(laser_points) if g]
    for gi, run_pts in enumerate(run_groups):
        width = run_pts[0].width
        segments = _split_at_slams(run_pts)

        # The next run's true (raw) start tick, if any - a run's *last*
        # point needs this as a ceiling too, not just the next point within
        # its own flattened list: nothing else stops the standard slam gap
        # from landing this run's end on or past the next run's start, which
        # would corrupt the output (two runs' points fighting over the same
        # row) or, short of that, close up the one-tick gap
        # LaserLane.anchors() relies on to keep them visually separate (see
        # its docstring). One extra tick of margin (`- 1`) reserves room for
        # that gap tick on top of just not colliding outright.
        next_true_start = run_groups[gi + 1][0].tick if gi + 1 < len(run_groups) else None

        # Flattened across every segment of this run (not just the current
        # one) so a slam's landing point can see the tick of whatever comes
        # right after it, even across a segment boundary - needed to back
        # off from a collision with the *next* slam in a dense chain.
        # `flat_curves` runs parallel to `flat` with one entry fewer: flat_curves[i] draws flat[i] -> flat[i+1]. The join *between* two segments is always a genuine slam (that is what _split_at_slams split on), and a slam is never a curve, so those joins get None.
        flat, flat_curves, tight = [], [], False
        for si, seg in enumerate(segments):
            meas, _ = tl.measure_of_tick(seg[0][0])
            mlen = tl.measure_length(meas)
            min_gap = max(1, mlen // min_gap_frac)
            # Every segment but the first starts *at* a slam's landing point, which the placement loop below writes `lead` ticks after this segment's own first tick - so the min-gap rule has to be measured from there, not from the raw shared tick (see _enforce_min_gap's `lead`). A chained same-tick stack (3+ points on one tick) technically stacks more than one gap onto the later segments' landings; not modelled here, since those landings are already collapsed to a tick apiece by the ceiling backoff in _slam_landing_tick.
            lead = 0 if si == 0 else (max(1, whole_note // slam_gap_frac) if slam_gap_frac else 1)
            if curves:
                kept, seg_curves, seg_tight = decimate_segment_curved(
                    seg, min_gap, lead=lead, max_leg=max(1, whole_note // CURVE_LEG_FRAC))
            else:
                kept, seg_tight = decimate_segment(seg, min_gap, lead=lead)
                seg_curves = [None] * max(0, len(kept) - 1)
            tight = tight or seg_tight
            if flat:
                flat_curves.append(None)      # the slam join into this segment
            flat.extend(kept)
            flat_curves.extend(seg_curves)

        points, slam_after = [], []
        for i, (t, v) in enumerate(flat):
            # flat[i] repeating the previous kept point's raw tick is
            # exactly a genuine vox same-tick slam (segment boundaries
            # duplicate their shared tick by construction - see
            # _split_at_slams) - give it its own line and mark the join.
            is_slam_landing = bool(points) and t == points[-1][0]
            if is_slam_landing:
                if slam_gap_frac:
                    gap = max(1, whole_note // slam_gap_frac)
                    if i + 1 < len(flat):
                        ceiling = flat[i + 1][0]
                    elif next_true_start is not None:
                        ceiling = next_true_start - 1
                    else:
                        ceiling = None
                    meas, _ = tl.measure_of_tick(points[-1][0])
                    # One tick past ksh's own slam cutoff - the least a
                    # trailing leg can be and still be unambiguously *not*
                    # a slam (see _slam_landing_tick's docstring for why
                    # this isn't the more conservative min_gap_frac).
                    safe_gap = max(1, tl.measure_length(meas) // KSH_SLAM_CUTOFF_FRAC) + 1
                    t = _slam_landing_tick(points[-1][0], used_ticks, gap, ceiling, safe_gap)
                else:
                    t = _bump_to_free_tick(t, used_ticks)
            else:
                used_ticks.add(t)
            if points:
                slam_after.append(is_slam_landing)
            points.append((t, v))

        out.append(Run(points, slam_after, width, tight, flat_curves))

    # A slam can land exactly on a run *boundary* instead of inside one
    # run's own point list: vox flags one run's true end and the next
    # run's true start at the identical tick (node_type 2 then 1, same
    # tick) - a real handoff, not the mid-run case _split_at_slams already
    # covers. Only one grid row exists per tick, and LaserLane.run_at()
    # resolves the tie toward whichever run *starts* there, so the earlier
    # run's true endpoint would otherwise never get a row of its own - the
    # output draws a straight line from that run's second-to-last point
    # clear through to the next run's landing value instead of a vertical
    # hold followed by an instant drop. Move the earlier run's endpoint one
    # tick earlier so it gets a row; found and fixed against
    # 2397_ultracharge_yutaimai (user-reported).
    for a, b in zip(out, out[1:]):
        if a.end_tick != b.start_tick:
            continue
        t, v = a.points[-1]
        floor = a.points[-2][0] if len(a.points) > 1 else a.points[0][0] - 1
        new_t = _bump_to_free_tick_before(t, used_ticks, floor)
        if new_t is not None:
            used_ticks.discard(t)
            a.points[-1] = (new_t, v)

    return out
