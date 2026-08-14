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
"""

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
    """

    __slots__ = ("points", "slam_after", "width", "tight")

    def __init__(self, points, slam_after, width, tight):
        self.points = points
        self.slam_after = slam_after
        self.width = width
        self.tight = tight

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
        rising = best_v >= prev_v
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


def build_runs(laser_points, tl, min_gap_frac=24, slam_gap_frac=SLAM_GAP_FRAC):
    """vox LaserPoint stream (one lane, already tick-sorted) -> [Run, ...].

    `min_gap_frac`: minimum point spacing enforced during decimation, as a
    fraction of the *local* measure length (1/24 by default - see the
    module docstring). Never applied across a genuine same-tick slam.

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
        flat, tight = [], False
        for si, seg in enumerate(segments):
            meas, _ = tl.measure_of_tick(seg[0][0])
            mlen = tl.measure_length(meas)
            min_gap = max(1, mlen // min_gap_frac)
            # Every segment but the first starts *at* a slam's landing point, which the placement loop below writes `lead` ticks after this segment's own first tick - so the min-gap rule has to be measured from there, not from the raw shared tick (see _enforce_min_gap's `lead`). A chained same-tick stack (3+ points on one tick) technically stacks more than one gap onto the later segments' landings; not modelled here, since those landings are already collapsed to a tick apiece by the ceiling backoff in _slam_landing_tick.
            lead = 0 if si == 0 else (max(1, whole_note // slam_gap_frac) if slam_gap_frac else 1)
            kept, seg_tight = decimate_segment(seg, min_gap, lead=lead)
            tight = tight or seg_tight
            flat.extend(kept)

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

        out.append(Run(points, slam_after, width, tight))

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
