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
import bisect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared"))


# --------------------------------------------------------------------------
# tilt
# --------------------------------------------------------------------------

# How many cells of complete laser silence (both lanes) before a run start
# counts as a fresh "section" worth pretilt-cancelling, vs just the next
# segment of an ongoing laser passage. 48 = 1 beat at the default 48/quarter
# resolution. See specs/camera.md "Tilt: pretilt cancellation".
PRETILT_SILENCE_MIN = 48

# Lead time (cells) before a fresh section's laser run where `tilt=0` gets
# inserted. The one cleanly-repeating example found (foolish_again/exh.ksh,
# 6/6 occurrences exact) used 24 - a somewhat arbitrary choice among the
# observed gaps (0, 24, 48, 96, 168, 192...) and flagged as such.
PRETILT_LEAD = 24


def _laser_run_starts(chart):
    """-> sorted [(tick, side_idx), ...] for every node_type==1 row."""
    out = []
    for side_idx, lst in enumerate(chart.laser):
        for p in lst:
            if p.node_type == 1:
                out.append((p.tick, side_idx))
    out.sort()
    return out


def _section_start_ticks(chart, silence_min=PRETILT_SILENCE_MIN):
    """-> sorted run-start ticks with no laser activity (either lane) in the
    `silence_min` cells right before - see specs/camera.md.
    """
    all_ticks = sorted(p.tick for lst in chart.laser for p in lst)
    out = []
    for (t, _side) in _laser_run_starts(chart):
        i = bisect.bisect_left(all_ticks, t)
        prev = all_ticks[i - 1] if i > 0 else None
        if prev is None or t - prev >= silence_min:
            out.append(t)
    return sorted(set(out))


def fmt_tilt(v):
    s = "%.3f" % v
    s = s.rstrip("0").rstrip(".")
    return s if s else "0"


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


def compute_tilt_events(chart, silence_min=PRETILT_SILENCE_MIN, lead=PRETILT_LEAD):
    """-> sorted [(tick, "tilt=<value>"), ...].

    Baseline is `tilt=normal` throughout (let ksh's own auto-tilt run, same
    as it does in the arcade for laser-driven tilt - see specs/camera.md;
    the auto-tilt *formula* itself isn't modelled here, only ksh's built-in
    version of it). Two things override that baseline:

    1. Pretilt cancellation: KSM's auto-tilt anticipates an upcoming laser
       before the arcade would, so at every fresh laser section start (not
       every run - see _section_start_ticks) this inserts `tilt=0` `lead`
       cells early, then `tilt=normal` right at the run start to hand back
       to KSM's auto-tilt once the real laser motion begins.
    2. Manual `Tilt` vox segments (9% of charts - specs/camera.md) are
       charter-authored camera work, passed through as literal floats at
       each segment's start/end tick, taking priority over both the
       baseline and any pretilt bracket that would otherwise land inside
       their span.
    """
    manual = chart.camera["tilt"]
    manual_ranges = [(s.tick, s.end_tick) for s in manual]

    def in_manual(t):
        return any(a <= t <= b for (a, b) in manual_ranges)

    # A manual segment's start/end are appended as two points per segment,
    # in that order, so a zero-length segment (tick == end_tick, a genuine
    # vox "instant snap") produces an [arrival, departure] pair at the same
    # tick rather than one silently overwriting the other - see
    # _place_track, which is what actually keeps them from colliding.
    points = [(0, "normal")]
    for seg in manual:
        points.append((seg.tick, fmt_tilt(seg.start)))
        points.append((seg.end_tick, fmt_tilt(seg.end)))

    # revert to normal after each manual block, unless another block
    # picks up exactly at that tick (node_type 3 "ends a series" is the
    # vox-side signal for this; re-deriving it from tick adjacency is
    # equivalent and needs no extra state).
    starts = set(a for (a, _b) in manual_ranges)
    for (_a, b) in manual_ranges:
        if b not in starts:
            points.append((b, "normal"))

    for t in _section_start_ticks(chart, silence_min):
        if in_manual(t):
            continue
        lead_tick = max(0, t - lead)
        if not in_manual(lead_tick):
            points.append((lead_tick, "0"))
        points.append((t, "normal"))

    return _dedupe_consecutive(_place_track(points))


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

# vox "roll" (1,2,3,4,6,7) -> ksh full spin @(/@); vox "swing" (5) -> ksh
# half spin @</@> - confirmed 66/66 against the reference set (kind) and
# 66/66 (direction, see below). S</S> intentionally never emitted: unused
# in every reference chart even for genuine vox swings - specs/camera.md.
SWING_ROLL_TYPE = 5

# vox_format.md's named default duration per roll_type, in "beats" - used
# only when C8 (roll_length) is 0, i.e. vox says "use this type's normal
# length". Types 6/7 aren't named this way (6 gives its length in 1/32
# notes instead, and is never 0 in observed data; 7 is undocumented) so
# they aren't in this table - see compute_spin_tokens.
DEFAULT_BEATS = {1: 6, 2: 2, 3: 3, 4: 12, 5: 3}

# ksh 192nds per vox "beat" unit, fit against scripts/camera/correlate.py's
# roll_type=1 samples with an explicit C8 (3,6,9 all landed on an exact
# multiple of this - see specs/camera.md "Spin/swing: length"). Applied
# uniformly to every roll_type except 6, which vox_format.md documents as
# using 1/32-note units instead (-> 192/32 = 6 ksh-192nds per unit).
BEAT_TO_KSH192 = 32
TYPE6_UNIT_TO_KSH192 = 6   # 1/32 note, in a 4/4 measure


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


def compute_spin_tokens(chart):
    """-> {tick: (side_idx, "@(24")}. `side_idx` is 0=L, 1=R - the caller
    decides what to do if both lanes want a spin on the same tick (ksh's
    chart-line format has exactly one lane-spin slot per line); this
    function always returns only the first one found per tick and the
    caller is expected to at least count/report drops rather than silently
    picking one, per this project's rule on lossy conversions.
    """
    tokens = {}
    for side_idx, lst in enumerate(chart.laser):
        for i, p in enumerate(lst):
            if p.roll_type == 0:
                continue
            dirsign = _outgoing_dirsign(lst, i)
            if dirsign is None:
                continue
            is_swing = p.roll_type == SWING_ROLL_TYPE
            if is_swing:
                base = "@<" if dirsign < 0 else "@>"
            else:
                base = "@(" if dirsign < 0 else "@)"

            if p.roll_type == 6:
                length = (p.roll_length or 0) * TYPE6_UNIT_TO_KSH192
            elif p.roll_length:
                length = p.roll_length * BEAT_TO_KSH192
            else:
                length = DEFAULT_BEATS.get(p.roll_type, 3) * BEAT_TO_KSH192
            length = max(1, int(round(length)))

            tokens.setdefault(p.tick, (side_idx, "%s%d" % (base, length)))
    return tokens


if __name__ == "__main__":
    import vox as voxmod
    if len(sys.argv) < 2:
        raise SystemExit("usage: camera.py <chart.vox>")
    chart = voxmod.load(sys.argv[1])
    tilt = compute_tilt_events(chart)
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
