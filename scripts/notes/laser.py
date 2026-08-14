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

A true vox slam - two points at the identical tick - is different from all
of the above: it is not a curve to approximate, it is a real instantaneous
jump, and both values must survive untouched. Ksh has no "same row, two
values" - the second point needs a tick of its own. By default it lands
`SLAM_GAP_FRAC` (1/64 of the local measure) after the first, matching how
real hand-charted slams are spaced and staying comfortably inside ksh's own
1/32-or-shorter slam-recognition cutoff - not just the very next free tick,
which technically works too but renders as a near-invisible hairline next
to a normal hand-charted slam and forces that measure's grid down to
near-native resolution just to place one point (see convert.py's resolution
picker). A dense enough slam chain - 8 slams to a beat, i.e. 32nd-note
spacing, is the densest this project has seen - can leave less than 1/64 of
a measure between one slam's start and the next, in which case the standard
gap would land the first slam's end on or past the second slam's start;
`_slam_landing_tick` doesn't do anything clever about that, it just backs
the end off to one tick before the collision. The visual difference between
a slam landing 1/64 of a measure out and one tick out isn't perceptible,
and one tick of separation is all ksh actually needs to parse the two
points as distinct rows. `build_runs(..., slam_gap_frac=0)` - wired to the
CLI's `--no-slam-gap` and the GUI's "Standard slam gap" checkbox - turns
this off and goes back to the bare next-free-tick placement.

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

# Default gap, as a fraction of the local measure, from a genuine same-tick
# vox slam's start to where its end lands in the ksh output - see the module
# docstring's "true vox slam" paragraph. `build_runs(slam_gap_frac=0)`
# disables this and falls back to the old bare next-free-tick placement.
SLAM_GAP_FRAC = 64


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


def _enforce_min_gap(pts, min_gap):
    """Greedy left-to-right thinning so no two consecutive kept points are
    closer than `min_gap` ticks - except the run's true end, which is
    always kept regardless. Returns (kept_points, tight).

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
        return pts, False
    out = [pts[0]]
    dropped_after = {}   # index into `out` -> [(t, v), ...] dropped right after it
    for t, v in pts[1:-1]:
        if t - out[-1][0] >= min_gap:
            out.append((t, v))
        else:
            dropped_after.setdefault(len(out) - 1, []).append((t, v))
    last = pts[-1]
    while len(out) > 1 and last[0] - out[-1][0] < min_gap:
        out.pop()
    tight = (last[0] - out[-1][0]) < min_gap
    out.append(last)

    for i in range(1, len(out) - 1):
        cands = dropped_after.get(i, ())
        if not cands:
            continue
        prev_v = out[i - 1][1]
        best_t, best_v = out[i]
        rising = best_v >= prev_v
        for t, v in cands:
            more_extreme = (rising and v >= best_v) or (not rising and v <= best_v)
            if (more_extreme and t - out[i - 1][0] >= min_gap
                    and out[i + 1][0] - t >= min_gap):
                best_t, best_v = t, v
        out[i] = (best_t, best_v)

    return out, tight


def decimate_segment(pts, min_gap, tol=RDP_TOL):
    """One slam-free stretch of a run -> (kept_points, tight)."""
    return _enforce_min_gap(_rdp(pts, tol), min_gap)


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


def _slam_landing_tick(start_t, used, gap, ceiling=None):
    """Target tick for a genuine same-tick slam's second point: `gap` ticks
    after `start_t` (see SLAM_GAP_FRAC / the module docstring), backed off
    to fit when there isn't room for the full gap.

    `ceiling`, when given, is the tick of whatever point comes next in the
    run (not yet placed itself) - the standard gap must land strictly
    before it, or a dense slam chain would have this slam's end overlap the
    next slam's start. No attempt is made to renegotiate room further back;
    landing one tick before the collision is enough (see docstring).
    """
    target = start_t + max(1, gap)
    if ceiling is not None and target >= ceiling:
        target = ceiling - 1
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

    `slam_gap_frac`: a genuine same-tick slam's start-to-end gap, as a
    fraction of the local measure (1/64 by default - see SLAM_GAP_FRAC and
    the module docstring's "true vox slam" paragraph). 0 (or any other
    falsy value) instead places the slam's end on the very next free tick,
    the older, thinner behaviour.
    """
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
        for seg in segments:
            meas, _ = tl.measure_of_tick(seg[0][0])
            min_gap = max(1, tl.measure_length(meas) // min_gap_frac)
            kept, seg_tight = decimate_segment(seg, min_gap)
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
                    meas, _ = tl.measure_of_tick(t)
                    gap = max(1, tl.measure_length(meas) // slam_gap_frac)
                    if i + 1 < len(flat):
                        ceiling = flat[i + 1][0]
                    elif next_true_start is not None:
                        ceiling = next_true_start - 1
                    else:
                        ceiling = None
                    t = _slam_landing_tick(points[-1][0], used_ticks, gap, ceiling)
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
