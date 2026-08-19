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


def compute_tilt_events(chart, pretilt_fix=False, min_factor=PRETILT_MIN_FACTOR):
    """-> sorted [(tick, "tilt=<value>"), ...].

    Baseline is `tilt=normal` throughout (let ksh's own auto-tilt run, same
    as it does in the arcade for laser-driven tilt - see specs/camera.md;
    the auto-tilt *formula* itself isn't modelled here, only ksh's built-in
    version of it). Manual `Tilt` vox segments (9% of charts -
    specs/camera.md) are charter-authored camera work and override that
    baseline, passed through as literal floats at each segment's start/end
    tick.

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

    combined = placed + reverts
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

# vox "roll" (1,2,3,4,6,7) -> ksh full spin @(/@); vox "swing" (5) -> ksh
# half spin @</@> - confirmed 66/66 against the reference set (kind) and
# 66/66 (direction, see below). S</S> intentionally never emitted: unused
# in every reference chart even for genuine vox swings - specs/camera.md.
SWING_ROLL_TYPE = 5

# vox_format.md's named default duration per roll_type, in quarter notes -
# used only when the length column (roll_length) is 0, i.e. vox says "use
# this type's normal length". All four types with reference coverage (1, 2, 3, 5)
# confirm their name against the hand charts once the per-song charter
# scale is controlled for; type 4 has one sample and is unvalidated. Types
# 6/7 aren't named this way - they always carry an explicit length - so
# they aren't in this table; see compute_spin_tokens.
DEFAULT_BEATS = {1: 6, 2: 2, 3: 3, 4: 12, 5: 3}

# The spin-length law, fit against 1354 reference samples by
# scripts/camera/correlate.py's spin_length_report: a ksh spin token's
# length is exactly HALF the duration vox declares, in ksh 192nds.
#
# vox states roll lengths in quarter notes and its number covers the whole
# motion *including the overshoot*, where ksh's number covers only the part
# before the overshoot (vox_format.md C3) - and the overshoot turns out to
# take exactly as long as the rotation it follows. So one vox quarter note
# = 48 ksh-192nds of declared duration -> 24 ksh-192nds of ksh spin length.
BEAT_TO_KSH192 = 24

# Types 6/7 are the "8x speed" rolls: their length column counts 1/32
# notes, i.e. 1/8 of a quarter note, so the same law lands on 24/8 = 3.
# This one is not a modal estimate - the reference charts transcribe type 6
# machine-exactly (C8 of 13/17/23/33/37 -> ksh 39/51/69/99/111, numbers no
# charter picks by feel), 61/64 exact.
TYPE67_UNIT_TO_KSH192 = 3   # 1/32 note

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

    `p.roll_length` is the version-resolved length column (C8 up to format
    12, C9 from 13). Every 6/7 row in the corpus carries an explicit length
    in it, so the `or 0` below is unreachable in practice and there is no
    documented default duration for those two types to fall back on.
    """
    if p.roll_type in (6, 7):
        length = (p.roll_length or 0) * TYPE67_UNIT_TO_KSH192
    elif p.roll_length:
        length = p.roll_length * BEAT_TO_KSH192
    else:
        length = DEFAULT_BEATS.get(p.roll_type, 3) * BEAT_TO_KSH192
    return max(1, int(round(length)))


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
