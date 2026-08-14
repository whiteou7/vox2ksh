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


def compute_tilt_events(chart):
    """-> sorted [(tick, "tilt=<value>"), ...].

    Baseline is `tilt=normal` throughout (let ksh's own auto-tilt run, same
    as it does in the arcade for laser-driven tilt - see specs/camera.md;
    the auto-tilt *formula* itself isn't modelled here, only ksh's built-in
    version of it). Manual `Tilt` vox segments (9% of charts -
    specs/camera.md) are charter-authored camera work and override that
    baseline, passed through as literal floats at each segment's start/end
    tick.
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

# vox_format.md's named default duration per roll_type, in quarter notes -
# used only when C8 (roll_length) is 0, i.e. vox says "use this type's
# normal length". All four types with reference coverage (1, 2, 3, 5)
# confirm their name against the hand charts once the per-song charter
# scale is controlled for; type 4 has one sample and is unvalidated. Types
# 6/7 aren't named this way - they always carry an explicit length in C8
# (or C9 in v13) - so they aren't in this table; see compute_spin_tokens.
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

# In chart format 13 the types-6/7 length simply MOVED from C8 to C9: the
# two distributions are the same quantity in the same unit (v12 C8 vs v13
# C9 for type 6: quartiles [5,12,15,25,135] vs [3,12,15,25,35], means 17.7
# vs 18.2), so no separate scale factor applies - see specs/camera.md. C9
# on types 1-5 is the unrelated "cells per chain" (median 3) and must not
# be read as a length, which is why this path is restricted to 6/7.


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

    Types 6/7 read their length from C9 instead of C8 on format-13 charts,
    where the column moved. The four v13 rows that carry *both* are the
    reason this prefers C9 outright rather than "C8 if present": their C8
    is 1 or 2 (a 3-to-6 tick spin, i.e. nothing) next to a C9 of 10-30,
    squarely in the normal length range - C8 is vestigial there. The
    version test is what keeps that preference off v12, where the only
    rows carrying both are one charter's (`littleredridinghood`) genuine
    cells-per-chain C9=3 alongside a real C8 length of 7-15.
    """
    if p.roll_type in (6, 7):
        units = (p.cells_per_chain if chart.version >= 13 and p.cells_per_chain
                 else p.roll_length or p.cells_per_chain)
        # No corpus row reaches the fallback: every 6/7 row in every version
        # carries a length in one column or the other.
        length = (units or 0) * TYPE67_UNIT_TO_KSH192
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
