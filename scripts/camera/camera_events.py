#!/usr/bin/env python3
"""Tilt, zoom and spin conversion (specs/camera.md): compute_tilt_events, compute_zoom_events and compute_spin_tokens. Pure functions over a loaded VoxChart, no file I/O.
"""
import sys


def format_tilt(v):
    s = "%.3f" % v
    s = s.rstrip("0").rstrip(".")
    if s in ("", "-0", "-"):
        return "0"
    return s


TILT_VOX_TO_KSH = -1.5


_NO_VALUE = object()


def _separate_same_tick_values(points):
    points = sorted(points, key=lambda p: p[0])
    out = []
    group_start, count = 0, len(points)
    while group_start < count:
        tick = points[group_start][0]
        cursor = group_start
        placed_tick = tick
        last_value = _NO_VALUE
        while cursor < count and points[cursor][0] == tick:
            value = points[cursor][1]
            if value != last_value:
                if last_value is not _NO_VALUE:
                    placed_tick += 1
                out.append((placed_tick, value))
                last_value = value
            cursor += 1
        group_start = cursor
    return out


PRETILT_WINDOW_BEATS = 2.0

PRETILT_LEAD_BEATS = 0.5

PRETILT_SNAP_BEATS = 0.25


def _laser_spans(points, home):
    out = []
    section = None
    for point in points:
        at_home = abs(point.pos - home) < 1e-6
        if point.node_type == 1 or section is None:
            if section is not None:
                out.append(tuple(section))
            section = [point.tick, point.pos, point.tick, at_home]
        else:
            section[2] = point.tick
            section[3] = section[3] and at_home
        if point.node_type == 2:
            out.append(tuple(section))
            section = None
    if section is not None:
        out.append(tuple(section))
    return out


def _pretilt_brackets(chart):
    tl = chart.tl
    window = max(1, int(round(PRETILT_WINDOW_BEATS * tl.res)))
    lead = max(0, int(round(PRETILT_LEAD_BEATS * tl.res)))
    snap = max(1, int(round(PRETILT_SNAP_BEATS * tl.res)))
    sections = [(lane, s, pos, e, home)
                for lane, pts in enumerate(chart.laser)
                for (s, pos, e, home) in _laser_spans(pts, 0.0 if lane == 0 else 1.0)]
    manual = [(seg.tick, seg.end_tick) for seg in chart.camera["tilt"]]

    def snap_to_grid_down(t):
        m, off = tl.measure_and_offset(t)
        return tl.measure_start_tick(m) + (off // snap) * snap

    out = []
    for (lane, start, pos, _end, _home) in sections:
        factor = pos if lane == 0 else 1.0 - pos
        if factor <= 0.0:
            continue
        window_start = start - window
        # A straight laser resting on the other lane's home edge adds no tilt,
        # so it neither blocks nor bounds the bracket.
        spans = [(s, e) for (l, s, _pos, e, home) in sections
                 if l == lane or not home]
        if any(a < start and b > window_start for (a, b) in spans):
            continue
        if any(a <= start and b >= window_start for (a, b) in manual):
            continue
        prev_end = max((b for (_a, b) in spans if b <= window_start), default=None)
        open_tick = max(0, snap_to_grid_down(start - window - lead))
        if prev_end is not None and prev_end > open_tick:
            open_tick = prev_end
        if open_tick >= start:
            continue
        out.append((open_tick, start))

    out = sorted(set(out))
    merged = []
    for (a, b) in out:
        if merged and a < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            continue
        merged.append((a, b))
    return merged


def _triple_spin_tilt_points(chart):
    ramp, restore, spans = [], [], []
    seen = set()
    for points in chart.laser:
        for index, point in enumerate(points):
            if point.roll_type != TRIPLE_ROLL_TYPE or point.tick in seen:
                continue
            direction = _outgoing_direction(points, index)
            if direction is None:
                continue
            seen.add(point.tick)
            span = int(round(triple_declared_beats(point) * chart.res))
            if span <= 0:
                continue
            magnitude = TRIPLE_TILT_MAGNITUDE if direction < 0 else -TRIPLE_TILT_MAGNITUDE
            ramp.append((point.tick, "0"))
            ramp.append((point.tick + span, "%d" % magnitude))
            restore.append((point.tick + span, "0"))
            restore.append((point.tick + span + 1, "normal"))
            spans.append((point.tick, point.tick + span))
    return ramp, restore, spans


def compute_tilt_events(chart, pretilt_fix=False):
    manual = chart.camera["tilt"]
    manual_ranges = [(s.tick, s.end_tick) for s in manual]

    points = [(0, "normal")]
    for seg in manual:
        points.append((seg.tick, format_tilt(TILT_VOX_TO_KSH * seg.start)))
        points.append((seg.end_tick, format_tilt(TILT_VOX_TO_KSH * seg.end)))

    if pretilt_fix:
        for (open_tick, close_tick) in _pretilt_brackets(chart):
            points.append((open_tick, "zero"))
            points.append((close_tick, "normal"))

    spin_ramp, spin_restore, spin_spans = _triple_spin_tilt_points(chart)

    def _inside_ramp(tick):
        return any(a < tick < b for (a, b) in spin_spans)

    dropped = 0
    if spin_spans:
        kept = [pt for pt in points if not _inside_ramp(pt[0])]
        dropped += len(points) - len(kept)
        points = kept
    points.extend(spin_ramp)

    placed = _collapse_equal_runs(_separate_same_tick_values(points))

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

    combined = placed + reverts + spin_restore
    combined.sort(key=lambda p: p[0])
    return _collapse_equal_runs(combined)


def _collapse_equal_runs(items):
    count = len(items)
    out = []
    for index, (tick, value) in enumerate(items):
        previous_value = items[index - 1][1] if index > 0 else None
        next_value = items[index + 1][1] if index + 1 < count else None
        if value != previous_value or value != next_value:
            out.append((tick, value))
    return out


ROTX_TO_ZOOM_TOP = 140.0
RADI_TO_ZOOM_BOTTOM = -125.0


def compute_zoom_events(chart, rotx_scale=ROTX_TO_ZOOM_TOP, radi_scale=RADI_TO_ZOOM_BOTTOM):
    def zoom_track(segs, key, scale):
        points = []
        for seg in segs:
            points.append((seg.tick, int(round(scale * seg.start))))
            points.append((seg.end_tick, int(round(scale * seg.end))))
        for (tick, val) in _collapse_equal_runs(_separate_same_tick_values(points)):
            yield (tick, "%s=%d" % (key, val))

    out = list(zoom_track(chart.camera["cam_rotx"], "zoom_top", rotx_scale))
    out += list(zoom_track(chart.camera["cam_radi"], "zoom_bottom", radi_scale))
    out.sort()
    return out


SWING_ROLL_TYPES = (5, 7)

TRIPLE_ROLL_TYPE = 4

TRIPLE_TILT_MAGNITUDE = 72

TRIPLE_BEAT_TO_KSH192 = 48

DEFAULT_BEATS = {1: 6, 2: 2, 3: 3, 4: 12, 5: 3, 6: 7, 7: 3}

BEAT_TO_KSH192 = 24

TYPE67_UNIT_TO_KSH192 = 3


def _outgoing_direction(points, index, max_lookahead=5):
    base = points[index].pos
    for later in range(index + 1, min(index + 1 + max_lookahead, len(points))):
        if points[later].pos != base:
            return (points[later].pos > base) - (points[later].pos < base)
    return None


def _spin_length_ksh192(chart, point):
    if point.roll_type == TRIPLE_ROLL_TYPE:
        length = triple_declared_beats(point) * TRIPLE_BEAT_TO_KSH192
    elif point.roll_type in (6, 7):
        length = (point.roll_length * TYPE67_UNIT_TO_KSH192 if point.roll_length
                  else DEFAULT_BEATS[point.roll_type] * BEAT_TO_KSH192)
    elif point.roll_length:
        length = point.roll_length * BEAT_TO_KSH192
    else:
        length = DEFAULT_BEATS.get(point.roll_type, 3) * BEAT_TO_KSH192
    return max(1, int(round(length)))


def triple_declared_beats(point):
    return point.roll_length if point.roll_length else DEFAULT_BEATS[TRIPLE_ROLL_TYPE]


def compute_spin_tokens(chart):
    tokens = {}
    for side_idx, points in enumerate(chart.laser):
        for index, point in enumerate(points):
            if point.roll_type == 0:
                continue
            direction = _outgoing_direction(points, index)
            if direction is None:
                continue
            is_swing = point.roll_type in SWING_ROLL_TYPES
            if is_swing:
                glyph = "@<" if direction < 0 else "@>"
            else:
                glyph = "@(" if direction < 0 else "@)"

            length = _spin_length_ksh192(chart, point)

            tokens.setdefault(point.tick, (side_idx, "%s%d" % (glyph, length)))
    return tokens


if __name__ == "__main__":
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "shared"))
    import vox_parser as voxmod
    argv = [a for a in sys.argv[1:] if a != "--pretilt-fix"]
    if not argv:
        raise SystemExit("usage: camera_events.py <chart.vox> [--pretilt-fix]")
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
