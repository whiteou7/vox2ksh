#!/usr/bin/env python3
"""
.vox -> .ksh camera events: tilt, top/bottom zoom, lane-spin. Pure compute -
these functions take a loaded `shared.vox.VoxChart` and return tick-tagged
events; `notes/convert.py` (via `camera=True`) is what actually places them
into the chart-line grid, since that grid is shared with the note data.

Scope and every number/formula here is explained in specs/camera.md - this
module is the executable form of that writeup, not a separate source of
truth. Read the "Tilt", "Zoom" and "Spin/swing" sections there before
changing any constant below; most of them are honest approximations from a
30-chart hand-charted reference set, not exact transcriptions, and
specs/camera.md says which is which.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared"))


# --------------------------------------------------------------------------
# tilt
# --------------------------------------------------------------------------

def fmt_tilt(v):
    s = "%.3f" % v
    s = s.rstrip("0").rstrip(".")
    if s in ("", "-0", "-"):
        return "0"      # -1.0 * 0.0 is -0.0 in Python; don't write "-0" out
    return s

TILT_VOX_TO_KSH = -1.5


def _place_track(points):
    """[(tick, value), ...], possibly with several different values stacked
    on the same tick, -> the same points with same-tick collisions resolved
    by spacing distinct values 1 cell apart (in their original relative
    order - `sorted` is stable, so this preserves vox's own file order for
    ties, which is what makes a same-tick "arrive at X, then instantly
    become Y" snap meaningful in the first place).

    This is the camera-track equivalent of notes.md bug #3 ("a same-tick
    slam landing on a run boundary lost its true endpoint entirely, drawing
    a diagonal instead of a vertical drop"): a vox camera/tilt segment can
    be zero-length (tick == end_tick) specifically to represent an instant
    jump, and a naive `events[tick] = value` write per segment silently lets
    the second write clobber the first, erasing the peak/trough the jump
    was arriving at or from. ksh has no same-tick equivalent of two
    different values, so the fix is the same shape as the laser one: two
    adjacent grid lines a cell apart instead of one.
    """
    points = sorted(points, key=lambda p: p[0])
    out = []
    i, n = 0, len(points)
    _unset = object()
    while i < n:
        tick = points[i][0]
        j = i
        cur_tick = tick
        last = _unset
        while j < n and points[j][0] == tick:
            v = points[j][1]
            if v != last:
                if last is not _unset:
                    cur_tick += 1   # a real value change at this vox tick - needs its own grid line
                out.append((cur_tick, v))
                last = v
            j += 1
        i = j
    return out


# --------------------------------------------------------------------------
# pretilt removal
# --------------------------------------------------------------------------
#
# KSM's auto-tilt anticipates lasers: HighwayTiltAuto.cpp's updateTiltFactor
# falls back to `FirstInRange(lane, pulse, pulse + kson::kResolution4 / 2)`
# whenever a lane has no section under the crit line, and tilts to that
# upcoming section's FIRST point value already. The arcade does not - its
# lane stays flat until the laser arrives - so a straight conversion tilts
# early, for up to half a measure, over notes the player is still reading.
# specs/camera.md's "Pretilt: KSM's two-beat laser anticipation" has the
# mechanism, the measured reference-charter idiom this reproduces, and the
# caveats (KSM v2 source, not the v1.6x binary).
#
# kResolution = 240 and kResolution4 = 960, so the window is 480 kson
# pulses = 2 quarter notes = half a 4/4 measure.
#
# Every length here is in QUARTER NOTES, not ticks, and is multiplied by the
# chart's own `tl.res` at use. This module works in vox ticks (notes/
# convert.py never rescales - it derives each measure's line count straight
# from `tl.measure_length`), and `#BEAT RESOLUTION` is per chart: 480 on the
# charts checked, 48 if the header is missing. A hardcoded tick count would
# silently mean a different musical duration on a chart with a different
# resolution - the first version of this had exactly that bug, sized in ksh
# 192nds, producing 1/5-beat brackets against a 480-tick chart.
PRETILT_WINDOW_BEATS = 2.0

# `tilt=zero` is not instant: it drives the auto-tilt *scale* toward 0 at
# kTiltScaleInterpolationSpeed = 4.0, i.e. roughly a quarter second of fade.
# Opening the bracket half a beat before the anticipation window lets that
# fade finish first, instead of racing the pretilt it is meant to suppress.
# (The reference charters' flat regions run a 3-beat median for the same
# reason, snapped to musical boundaries rather than computed.)
PRETILT_LEAD_BEATS = 0.5

# |tilt factor| the upcoming section would produce - `pos` for the left
# lane, `1 - pos` for the right, straight out of the engine's
# `tiltFactor += isLeftLaser ? v : -(1.0 - v)`. A section opening at its own
# home edge scores 0 and pretilts not at all; centre openings score 0.5 and
# crossed ones approach 1.0. 0.25 is the default cut because it excludes
# home-edge openings (which need no fix) while keeping every centre and
# crossed opening - the buckets where the reference charters actually
# intervene, 31-50% of the time against a 12.8% floor (specs/camera.md).
PRETILT_MIN_FACTOR = 0.25

# Grid grain the bracket's opening tick is snapped down to, in quarter
# notes (1/16 note). The closing tick is a laser run start and is already a
# grid anchor, but the opening tick is computed, and an arbitrary offset
# would force notes/convert.py's measure_resolution to a much finer grid
# for one option line. Snapping down only ever moves it earlier, which is
# harmless - the lane is already flat there.
PRETILT_SNAP_BEATS = 0.25


def _laser_sections(points):
    """vox LaserPoint stream -> [(start_tick, start_pos, end_tick), ...].

    Same segmentation rule as notes/laser.py's `_split_into_runs` (a run
    starts at node_type==1 or at the first point in the track, and ends
    inclusive at node_type==2) - duplicated rather than imported to keep
    the camera module free of a dependency on the notes one, since all it
    needs from a run is its two ticks and its first position.
    """
    out = []
    cur = None
    for p in points:
        if p.node_type == 1 or cur is None:
            if cur is not None:
                out.append((cur[0], cur[1], cur[2]))
            cur = [p.tick, p.pos, p.tick]
        else:
            cur[2] = p.tick
        if p.node_type == 2:
            out.append((cur[0], cur[1], cur[2]))
            cur = None
    if cur is not None:
        out.append((cur[0], cur[1], cur[2]))
    return out


def _pretilt_brackets(chart, min_factor=PRETILT_MIN_FACTOR):
    """-> [(open_tick, close_tick), ...], the spans to hold the lane flat.

    A laser section qualifies when both engine conditions hold: its own
    lane has been idle long enough for the look-ahead branch to fire, and
    its first point is far enough from that lane's home edge to move the
    lane visibly.

    The window is required to be clear of laser sections on *both* lanes,
    not just this one, because ksh's `tilt` is global while KSM's
    look-ahead is per lane. A lane anticipating its next section while the
    *other* lane holds a real laser is genuine pretilt too, but flattening
    there would kill the other lane's arcade-correct tilt along with it -
    that case is left alone deliberately, and is the known gap in this fix.
    """
    tl = chart.tl
    window = max(1, int(round(PRETILT_WINDOW_BEATS * tl.res)))
    lead = max(0, int(round(PRETILT_LEAD_BEATS * tl.res)))
    snap = max(1, int(round(PRETILT_SNAP_BEATS * tl.res)))
    sections = [(lane, s, pos, e)
                for lane, pts in enumerate(chart.laser)
                for (s, pos, e) in _laser_sections(pts)]
    spans = [(s, e) for (_lane, s, _pos, e) in sections]
    manual = [(seg.tick, seg.end_tick) for seg in chart.camera["tilt"]]

    def snap_down(t):
        m, off = tl.measure_of_tick(t)
        return tl.measure_start_tick(m) + (off // snap) * snap

    out = []
    for (lane, start, pos, _end) in sections:
        factor = pos if lane == 0 else 1.0 - pos
        if factor < min_factor:
            continue
        win = start - window
        # Anything overlapping the window - including this section's own
        # lane-mate starting at the same tick - blocks the bracket. A span
        # starting exactly at `start` is not overlapping (a < start is
        # False), which is what lets both lanes of a simultaneous pair
        # produce the same bracket rather than cancelling each other.
        if any(a < start and b > win for (a, b) in spans):
            continue
        if any(a <= start and b >= win for (a, b) in manual):
            continue        # charter-authored tilt owns this span already
        prev_end = max((b for (_a, b) in spans if b <= win), default=None)
        # Clamped at 0: notes/convert.py only walks measures from 0, so a
        # negative tick would drop the opening line and leave a dangling
        # restore behind. A chart opening on a laser inside the first two
        # beats is exactly that case.
        open_tick = max(0, snap_down(start - window - lead))
        if prev_end is not None and prev_end > open_tick:
            # Never open the bracket inside the previous laser: that tilt is
            # real. Landing exactly on its last point is also what the
            # reference conversions do (42.3% of their flattening events sit
            # within a quarter beat of a laser end).
            open_tick = prev_end
        if open_tick >= start:
            continue
        out.append((open_tick, start))

    out = sorted(set(out))
    merged = []
    for (a, b) in out:
        # Two brackets can only overlap when a qualifying section sits
        # inside another's flat span; keep the earlier one whole rather
        # than interleaving zero/normal pairs out of order.
        if merged and a < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            continue
        merged.append((a, b))
    return merged


def _triple_spin_tilt_points(chart):
    """-> ([(tick, value), ...], [(tick, "normal"), ...], [(start, end), ...])
    - the manual-tilt ramp that carries vox roll_type 4's extra turns, split
    into the points that go through `_place_track`, the hand-back that must
    stack on the ramp's own last tick rather than take a grid cell of its
    own, and the tick spans the ramps occupy (which the caller clears of
    everything else - see `compute_tilt_events`).

    ksh cannot express a triple spin as three spin tokens: KSM starts a spin
    from `CamPatternMain::onLaserSlamJudged`, so a token only fires where a
    laser slam is judged, and a type-4 row has exactly one slam. The spin
    stays a single token and the rest of the rotation is driven manually:

        tick         tilt=0           <- ramp starts flat, at the slam
        tick + D     tilt=+/-72       <- linear ramp across the whole roll
        tick + D     tilt=0           <- stacked: drop the lane back to level
        tick + D + 1 tilt=normal      <- next cell: hand back to auto tilt

    with `D` the vox-declared duration in quarter notes (C8, or 12) - the
    full declared duration, settle included, not just the 3/4 the turns
    themselves occupy.

    Emitted only where `compute_spin_tokens` emits a token, and on the same
    conditions, so the ramp can never outlive a spin that was never placed:
    a point whose outgoing direction is unreadable is skipped in both, and
    at most one bracket lands per tick (ksh has one spin slot per line, so
    two lanes rolling on the same tick already collapse to one token).
    """
    ramp, restore, spans = [], [], []
    seen = set()
    for lst in chart.laser:
        for i, p in enumerate(lst):
            if p.roll_type != TRIPLE_ROLL_TYPE or p.tick in seen:
                continue
            dirsign = _outgoing_dirsign(lst, i)
            if dirsign is None:
                continue
            seen.add(p.tick)
            span = int(round(triple_declared_beats(p) * chart.res))
            if span <= 0:
                continue
            # dirsign < 0 is the clockwise `@(` case - see compute_spin_tokens.
            magnitude = TRIPLE_TILT_MAGNITUDE if dirsign < 0 else -TRIPLE_TILT_MAGNITUDE
            ramp.append((p.tick, "0"))
            ramp.append((p.tick + span, "%d" % magnitude))
            # The ramp's peak and the return to level stack on one tick (no
            # grid line between them - ksh's instant-transition idiom), and
            # the hand-back to auto tilt goes one cell later, so the level
            # value is actually held for a cell before auto takes over.
            restore.append((p.tick + span, "0"))
            restore.append((p.tick + span + 1, "normal"))
            spans.append((p.tick, p.tick + span))
    return ramp, restore, spans


def compute_tilt_events(chart, pretilt_fix=False, min_factor=PRETILT_MIN_FACTOR):
    """-> sorted [(tick, "tilt=<value>"), ...].

    Baseline is `tilt=normal` throughout (let ksh's own auto-tilt run, same
    as it does in the arcade for laser-driven tilt - see specs/camera.md;
    the auto-tilt *formula* itself isn't modelled here, only ksh's built-in
    version of it). Manual `Tilt` vox segments (9% of charts -
    specs/camera.md) are charter-authored camera work and override that
    baseline, passed through as literal floats at each segment's start/end
    tick.

    vox roll_type 4 (the triple spin) additionally gets a manual-tilt ramp
    here, because ksh's spin token can only turn the lane once - see
    `_triple_spin_tilt_points`. This one is not optional: without it a
    type-4 roll converts to a plain single spin and two thirds of the
    motion is simply lost.

    `pretilt_fix` additionally brackets every laser section KSM would tilt
    into early with `tilt=zero` ... `tilt=normal`, the restore landing on
    the section's own first point - the idiom measured off the hand-made
    reference conversions, see _pretilt_brackets and specs/camera.md. Off
    by default: it is a deliberate divergence from "emit what the vox says
    and let KSM do the rest", and it flattens a little more aggressively
    than the arcade's own slow relax does.
    """
    manual = chart.camera["tilt"]
    manual_ranges = [(s.tick, s.end_tick) for s in manual]

    # A manual segment's start/end are appended as two points per segment,
    # in that order, so a zero-length segment (tick == end_tick, a genuine
    # vox "instant snap") produces an [arrival, departure] pair at the same
    # tick rather than one silently overwriting the other - see
    # _place_track, which is what actually keeps them from colliding.
    points = [(0, "normal")]
    for seg in manual:
        points.append((seg.tick, fmt_tilt(TILT_VOX_TO_KSH * seg.start)))
        points.append((seg.end_tick, fmt_tilt(TILT_VOX_TO_KSH * seg.end)))

    if pretilt_fix:
        for (open_tick, close_tick) in _pretilt_brackets(chart, min_factor=min_factor):
            points.append((open_tick, "zero"))
            points.append((close_tick, "normal"))

    # A ramp is a linear interpolation from one endpoint to the other, so
    # ANY other tilt point landing strictly inside it breaks it: the value
    # gets pinned partway and the rotation the ramp exists to produce stops
    # happening. Real, not hypothetical - `2392_dementafterlegend_cosmograph_5m`
    # (format 13) has a manual `Tilt` series whose 0.0 -> 0.0 block ends 96
    # cells into a 144-cell ramp, which held the lane flat for two thirds of
    # the roll and handed back to auto-tilt before the ramp had done
    # anything. Per direction the ramp wins: it is carrying the spin, which
    # is the dominant motion, so the span is cleared of everything else
    # first. This is a genuine (if small) discard of chart data, so it is
    # counted and reported rather than done silently.
    spin_ramp, spin_restore, spin_spans = _triple_spin_tilt_points(chart)

    def _inside_ramp(tick):
        return any(a < tick < b for (a, b) in spin_spans)

    dropped = 0
    if spin_spans:
        kept = [pt for pt in points if not _inside_ramp(pt[0])]
        dropped += len(points) - len(kept)
        points = kept
    points.extend(spin_ramp)

    placed = _dedupe_consecutive(_place_track(points))

    # Revert to normal on each manual block's OWN last tick, not a grid
    # cell after it, unless another block picks up exactly at that tick
    # (node_type 3 "ends a series" is the vox-side signal for this;
    # re-deriving it from tick adjacency is equivalent and needs no extra
    # state). This deliberately bypasses _place_track's same-tick spacing:
    # that spacing is for genuine value collisions inside `points` above
    # (two different manual values both wanting the same vox tick), but a
    # revert never collides with anything - it is additional information
    # ("and now hand back to auto-tilt") layered onto a tick that already
    # has its real value placed. ksh has no trouble with that: option
    # lines stack on one tick with no note row between them, which is
    # exactly the "instant transition" idiom (`tilt=25` then `tilt=normal`
    # back to back) the reference charters use 892 times over - see
    # specs/camera.md - so spending an extra grid cell here would just be
    # a needless divergence from how real charts do it.
    starts = set(a for (a, _b) in manual_ranges)
    reverts = [(b, "normal") for (_a, b) in manual_ranges if b not in starts]
    if spin_spans:
        kept = [r for r in reverts if not _inside_ramp(r[0])]
        dropped += len(reverts) - len(kept)
        reverts = kept
    if dropped:
        print("note: dropped %d tilt point(s) falling inside a roll_type 4 "
              "spin ramp, which would have broken the ramp's interpolation "
              "(see specs/camera.md)" % dropped, file=sys.stderr)

    # The triple-spin ramp's hand-back rides the same path as those reverts,
    # and for the same reason: it is layered onto a tick that already has its
    # real value, so it stacks on that tick instead of spending a grid cell.
    # `combined` puts `placed` first and the sort is stable, so the ramp's
    # final value is always written before the `normal` that ends it.
    combined = placed + reverts + spin_restore
    combined.sort(key=lambda p: p[0])
    return _dedupe_consecutive(combined)


def _dedupe_consecutive(items):
    """[(tick, value), ...] sorted by tick -> same, minus any entry that is
    strictly interior to a run of 3+ equal-value points (both its neighbours
    have the same value, so it adds no information ksh's linear
    interpolation doesn't already reproduce from the run's first and last
    point alone).

    Keeps BOTH the first and the last point of every run - dropping only
    the first (a plain "differs from previous" filter, this function's
    original form) is wrong: the last point of a hold is what stops ksh
    from linearly interpolating straight through the hold into whatever
    ramp comes after it, collapsing the flat period away entirely. Found
    on `2226_gryphone_etia_5m.vox` measures 90-93: vox holds tilt at 1.0
    for ~335 cells then ramps to -1.0 over the next 48; dropping the hold's
    last point turned that into one long diagonal from peak to peak with no
    flat period at all - a different shape than the same-tick-snap bug
    fixed earlier, but the same class of "a middle point matters" mistake.
    """
    n = len(items)
    out = []
    for i, (t, v) in enumerate(items):
        prev_v = items[i - 1][1] if i > 0 else None
        next_v = items[i + 1][1] if i + 1 < n else None
        if v != prev_v or v != next_v:
            out.append((t, v))
    return out


# --------------------------------------------------------------------------
# zoom (top/bottom only - zoom_side is out of scope, see specs/camera.md)
# --------------------------------------------------------------------------

# Regression constants from scripts/camera/correlate.py's per-song fits
# against the 30-chart reference set - central tendency, NOT exact (the
# reference conversions are hand-made, not derived - see specs/camera.md
# "Reference charts are hand-made, not derived"). Confirmed solid: rotx
# correlates positively with zoom_top, radi correlates *negatively* with
# zoom_bottom (a real sign flip between the formats).
ROTX_TO_ZOOM_TOP = 140.0
RADI_TO_ZOOM_BOTTOM = -125.0


def compute_zoom_events(chart, rotx_scale=ROTX_TO_ZOOM_TOP, radi_scale=RADI_TO_ZOOM_BOTTOM):
    """-> sorted [(tick, "zoom_top=<int>"|"zoom_bottom=<int>"), ...].

    Vox's CAM_RotX/CAM_Radi segments are a contiguous piecewise-linear
    track *between* segments (one segment's end tick/value matches the
    next segment's start in every sample checked), and ksh's zoom_top/
    zoom_bottom behave the same way (linear graph between option lines) -
    but a segment can itself be zero-length with start != end, vox's way
    of encoding an instant jump (a real "arrive at X, then instantly
    become Y" snap, same idea as a laser slam). Both endpoints of every
    segment are placed via _place_track, which is what keeps a snap's two
    values from colliding on one grid line - see its docstring and
    specs/camera.md's "same-tick snap" note. Naively keeping only the
    start (plus the final segment's end) - this function's first version -
    silently dropped every mid-chart snap's arrival value.
    """
    def track(segs, key, scale):
        points = []
        for seg in segs:
            points.append((seg.tick, int(round(scale * seg.start))))
            points.append((seg.end_tick, int(round(scale * seg.end))))
        for (tick, val) in _dedupe_consecutive(_place_track(points)):
            yield (tick, "%s=%d" % (key, val))

    out = list(track(chart.camera["cam_rotx"], "zoom_top", rotx_scale))
    out += list(track(chart.camera["cam_radi"], "zoom_bottom", radi_scale))
    out.sort()
    return out


# --------------------------------------------------------------------------
# spin / swing
# --------------------------------------------------------------------------

# --- what the game itself does, read out of soundvoltex.dll ---------------
#
# `Game::AngleUpdater` (gameplay event kind 8) is the whole lane-spin system,
# and three exact facts come out of it. specs/camera.md "Spin/swing" carries
# the full derivation and the addresses; the short form:
#
# 1. The chart's roll_type is REMAPPED before the game ever uses it. The
#    laser builder (`FUN_1803b1180`, switch at 0x1803b1a0c) rewrites the vox
#    column into an internal "rotation kind": 1->1, 2->3, 3->2, 4->4, 5->5,
#    6->6, 7->7 - vox 2 and 3 swap places. Everything in this module is
#    stated in *vox* numbering; the DLL's constants are in internal
#    numbering, so the swap matters when re-reading the disassembly.
#
# 2. The total duration is `FUN_18011f320(kind, bpm, length)`, in seconds.
#    Every branch is a multiple of 60/bpm - one beat - so the duration is
#    purely musical, with no wall-clock term anywhere:
#      length == 0 (vox's "use this type's default"):
#        internal 1,6 -> 420/bpm = 7 beats;  2,5,7 -> 180/bpm = 3 beats
#        internal 3   -> 60/bpm+60/bpm = 2 beats;  4 -> 720/bpm = 12 beats
#      length != 0:
#        internal 6,7 -> (6/bpm)*length  = length TENTHS of a beat
#        everything else -> (60/bpm)*length = length beats
#
# 3. What happens during that duration is one of three curves, picked by
#    `Game::AngleUpdater::CurrentRotationEffect`'s three lambdas (dispatch at
#    0x1803a4a1e). With u = progress 0..1 and d = +/-1 for direction:
#      internal 4       `FUN_1803a64d0`  angle = d*1440*u while u < 3/4:
#                       THREE full turns, one per quarter of the duration,
#                       then a damped-sine settle over the last quarter.
#      internal 5,7     `FUN_1803a6350`  angle = d*80*sin(2.1*pi*u)*(1-u):
#                       a +/-61-degree swing that never completes a turn.
#      internal 1,2,3,6 `FUN_1803a6190`  angle = d*840*u while u < 3/7:
#                       ONE full turn in the first 3/7, then the same
#                       damped-sine settle over the remaining 4/7.
#
# So the roll/swing split is *not* "type 5 is the swing": internal 7 (= vox
# 7) runs the swing curve too. That is what SWING_ROLL_TYPES encodes.

# vox "roll" (1,2,3,4,6) -> ksh full spin @(/@); vox "swing" (5) and vox 7
# -> ksh half spin @</@>. The 5-is-a-swing half was confirmed 66/66 against
# the reference set (kind) and 66/66 (direction, see below); the 7-is-a-swing
# half has no reference coverage at all and comes from the lambda dispatch
# above - type 7 was previously emitted as a full spin on the inherited
# (wrong) assumption that it behaves like type 6. S</S> intentionally never
# emitted: unused in every reference chart even for genuine vox swings -
# specs/camera.md.
SWING_ROLL_TYPES = (5, 7)

# vox roll_type 4 is the triple spin: three complete turns back to back,
# each taking exactly a quarter of the declared duration, with the single
# overshoot only after the third (fact 3 above - and exactly what direct
# inspection of the 25 type-4 charts showed).
#
# ksh has no triple-spin token, and it cannot be faked with three
# consecutive spin tokens either: KSM starts a spin from
# `CamPatternMain::onLaserSlamJudged` (ksm-v2
# MusicGame/Camera/CamPattern/CamPatternMain.cpp), i.e. a spin token only
# fires when a laser *slam* is judged on that line. A type-4 row has one
# slam, so turns 2 and 3 have nothing to hang off and their tokens are
# inert. The spin therefore stays a single token, and the two extra turns
# are driven by a manual `tilt=` ramp instead - see compute_spin_tokens and
# specs/camera.md.
# (For the record, since the ramp below does not use it: the three turns
# each take a *quarter* of the declared duration, not a third - the last
# quarter is the settle, which is what `angle = d*1440*u for u < 3/4` says.)
TRIPLE_ROLL_TYPE = 4

# The manual-tilt ramp that stands in for the two turns the spin token
# cannot express. `tilt=` is a graph in ksh, linearly interpolated between
# points, and KSM's manual tilt path applies its value to the highway
# rotation directly (`m_radians = kTiltRadians * value`, no clamping -
# ksm-v2 MusicGame/Camera/HighwayTiltManual.cpp). So ramping the value from
# 0 to a large magnitude across the roll's declared duration rotates the
# lane continuously for as long as the roll lasts, on top of the one real
# spin the token triggers at the slam.
#
# Magnitude and sign are per direction: +72 for a clockwise spin (`@(`,
# ksh_format.md's "left, clockwise"), -72 for anticlockwise (`@)`). The
# magnitude is a tested value from the target KSM build, not derived here.
TRIPLE_TILT_MAGNITUDE = 72

# ...and the spin token that goes with the ramp is NOT halved the way every
# other type is. BEAT_TO_KSH192 halves because vox's declared duration
# covers the settle and ksh's (on the reference-set reading) does not - but
# here the token and the ramp are one composite effect, so the token has to
# END WHERE THE RAMP ENDS, at the full declared duration. 48 ksh-192nds per
# quarter note is that duration in ksh's own unit, and it lines up with the
# ramp's end tick (declared beats * chart.res cells) by construction,
# whatever the chart's #BEAT RESOLUTION is.
TRIPLE_BEAT_TO_KSH192 = 48

# The declared duration per roll_type when the length column (roll_length) is
# 0, in quarter notes - vox's "use this type's normal length".
#
# The game's own table, out of `FUN_18011f320`'s length==0 branch (fact 2
# above) mapped back through the internal-kind remap into vox numbering, is
#     {1: 7, 2: 2, 3: 3, 4: 12, 5: 3, 6: 7, 7: 3}
# and every entry except type 1's agrees with what the hand charts imply.
# Type 1 is left at the hand-chart 6 *on purpose*: the two disagreements
# cancel. This table feeds BEAT_TO_KSH192 below, which is the reference set's
# "ksh length = half the declared duration" scale, and the game's real
# rotation share is 3/7, not a half - so 6 beats halved and 7 beats times
# 3/7 both come out at exactly 3 beats of ksh spin. Changing this entry
# without also changing that scale would just make type 1 wrong. See
# specs/camera.md, "The scale question the DLL does not settle".
#
# Types 6 and 7 carry the DLL's values outright, since there is no
# hand-chart reading of them to weigh against: no reference chart covers
# either type's default, and no corpus row of either type reaches it (they
# all carry an explicit length). They are here so a chart that *does* use
# one converts sensibly instead of falling off the end - see _spin_length,
# which has to route them through BEAT_TO_KSH192 rather than
# TYPE67_UNIT_TO_KSH192, because the DLL states these two defaults in whole
# beats (`420/bpm`, `180/bpm`) while 6/7's *explicit* lengths are counted in
# tenths of a beat. Reading the default in the explicit column's unit would
# make it ten times too short.
DEFAULT_BEATS = {1: 6, 2: 2, 3: 3, 4: 12, 5: 3, 6: 7, 7: 3}

# The spin-length law, fit against 1354 reference samples by
# scripts/camera/correlate.py's spin_length_report: a ksh spin token's
# length is exactly HALF the duration vox declares, in ksh 192nds. So one
# vox quarter note = 48 ksh-192nds of declared duration -> 24 of ksh spin.
#
# The *reasoning* this constant used to carry is now known to be wrong on
# both sides, even though the number stays. It said vox's length covers the
# rotation plus an overshoot that takes exactly as long as the rotation,
# while ksh's covers only the part before the overshoot. Measured instead:
# SDVX completes its turn at 3/7 of the declared duration (fact 3 above),
# not a half; and KSM's own length is *also* rotation-plus-recovery, its
# turn completing at 360/675 = 0.533 of it (ksm-v2 CamPatternSpin.cpp), not
# rotation-only. Matching the two rotation rates exactly would want a scale
# of 38.6, not 24 - against ksm-v2 constants, while the reference charters
# worked against v1.6x. 24 is kept because it is the only one of the three
# candidate scales with 1354 samples behind it; picking between them needs
# a test chart played in the target KSM build. specs/camera.md, "The scale
# question the DLL does not settle", has the full argument.
BEAT_TO_KSH192 = 24

# Types 6/7 are the "8x speed" rolls. The reference charts transcribe type 6
# as if its length column counted 1/32 notes (1/8 of a quarter note), which
# puts the same halving law at 24/8 = 3 - and they do it machine-exactly
# (C8 of 13/17/23/33/37 -> ksh 39/51/69/99/111, numbers no charter picks by
# feel), 61/64 exact.
#
# The DLL disagrees about the unit: `(6/bpm)*length` makes it a *tenth* of a
# quarter note, not an eighth (fact 2 above). That is the same unresolved
# scale question as BEAT_TO_KSH192, so this stays on the measured value; the
# 64 type-6 reference samples are the only evidence either way, and they may
# themselves be echoing the 1/32-note folklore rather than judging by ear.
TYPE67_UNIT_TO_KSH192 = 3   # reference-set unit; the DLL's is 1/10 beat

# In chart format 13 the length column MOVED one place right, for every
# roll type - the game's row parser inserted a new column after the curve
# type and shifted the rest, without ever consulting the roll type. That
# resolution lives in shared/vox.py's parse_laser_track, so `p.roll_length`
# below is already the right column for the chart's version and nothing
# here needs a version test. See specs/vox_format.md and specs/camera.md.


def _outgoing_dirsign(lst, i, max_lookahead=5):
    """Sign of the first position change after point i - the roll/swing tag
    sits on the point immediately before a same-tick slam in every raw
    example inspected (specs/camera.md), so it's the *outgoing* movement
    that determines clockwise/counterclockwise, not the incoming one.
    """
    base = lst[i].pos
    for j in range(i + 1, min(i + 1 + max_lookahead, len(lst))):
        if lst[j].pos != base:
            return (lst[j].pos > base) - (lst[j].pos < base)
    return None


def _spin_length(chart, p):
    """A laser point's ksh spin length in 192nds, per the law above.

    `TRIPLE_ROLL_TYPE` is the one type that is not halved: its token has to
    end where its tilt ramp ends - see TRIPLE_BEAT_TO_KSH192.
    """
    if p.roll_type == TRIPLE_ROLL_TYPE:
        length = triple_declared_beats(p) * TRIPLE_BEAT_TO_KSH192
    elif p.roll_type in (6, 7):
        # Explicit length only - the default is in beats, not in this
        # type's own tenth-of-a-beat unit, so it falls through to the
        # shared default branch below. See DEFAULT_BEATS.
        length = (p.roll_length * TYPE67_UNIT_TO_KSH192 if p.roll_length
                  else DEFAULT_BEATS[p.roll_type] * BEAT_TO_KSH192)
    elif p.roll_length:
        length = p.roll_length * BEAT_TO_KSH192
    else:
        length = DEFAULT_BEATS.get(p.roll_type, 3) * BEAT_TO_KSH192
    return max(1, int(round(length)))


def triple_declared_beats(p):
    """vox roll_type 4's declared duration in quarter notes - C8, or the
    type's default when C8 is 0. Type 4 is the one type whose DLL default
    (12, from `FUN_18011f320`'s `720/bpm`) and hand-chart default agree, so
    both readings give the same number here.
    """
    return p.roll_length if p.roll_length else DEFAULT_BEATS[TRIPLE_ROLL_TYPE]


def compute_spin_tokens(chart):
    """-> {tick: (side_idx, "@(24")}. `side_idx` is 0=L, 1=R - the caller
    decides what to do if both lanes want a spin on the same tick (ksh's
    chart-line format has exactly one lane-spin slot per line); this
    function always returns only the first one found per tick and the
    caller is expected to at least count/report drops rather than silently
    picking one, per this project's rule on lossy conversions.

    Exactly one entry per rolling laser point, `TRIPLE_ROLL_TYPE` included:
    ksh cannot express its three turns as three tokens, because KSM only
    starts a spin where a laser slam is judged (see TRIPLE_ROLL_TYPE above).
    """
    tokens = {}
    for side_idx, lst in enumerate(chart.laser):
        for i, p in enumerate(lst):
            if p.roll_type == 0:
                continue
            dirsign = _outgoing_dirsign(lst, i)
            if dirsign is None:
                continue
            is_swing = p.roll_type in SWING_ROLL_TYPES
            if is_swing:
                base = "@<" if dirsign < 0 else "@>"
            else:
                base = "@(" if dirsign < 0 else "@)"

            length = _spin_length(chart, p)

            tokens.setdefault(p.tick, (side_idx, "%s%d" % (base, length)))
    return tokens


if __name__ == "__main__":
    import vox as voxmod
    argv = [a for a in sys.argv[1:] if a != "--pretilt-fix"]
    if not argv:
        raise SystemExit("usage: camera.py <chart.vox> [--pretilt-fix]")
    chart = voxmod.load(argv[0])
    tilt = compute_tilt_events(chart, pretilt_fix="--pretilt-fix" in sys.argv)
    zoom = compute_zoom_events(chart)
    spin = compute_spin_tokens(chart)
    print("tilt events: %d" % len(tilt))
    for t in tilt[:20]:
        print("  ", t)
    print("zoom events: %d" % len(zoom))
    for z in zoom[:20]:
        print("  ", z)
    print("spin tokens: %d" % len(spin))
    for k in sorted(spin)[:20]:
        print("  ", k, spin[k])
