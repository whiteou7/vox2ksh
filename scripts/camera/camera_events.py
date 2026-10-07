#!/usr/bin/env python3
"""Tilt, zoom and spin conversion (specs/camera.md): compute_tilt_events, compute_zoom_events and compute_spin_tokens. Pure functions over a loaded VoxChart, no file I/O.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared"))


def fmt_tilt(v):
    s = "%.3f" % v
    s = s.rstrip("0").rstrip(".")
    if s in ("", "-0", "-"):
        return "0"
    return s


TILT_VOX_TO_KSH = -1.5


def _place_track(points):
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
                    cur_tick += 1
                out.append((cur_tick, v))
                last = v
            j += 1
        i = j
    return out


PRETILT_WINDOW_BEATS = 2.0

PRETILT_LEAD_BEATS = 0.5

PRETILT_MIN_FACTOR = 0.25

PRETILT_SNAP_BEATS = 0.25


def _laser_sections(points):
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
        if any(a < start and b > win for (a, b) in spans):
            continue
        if any(a <= start and b >= win for (a, b) in manual):
            continue
        prev_end = max((b for (_a, b) in spans if b <= win), default=None)
        open_tick = max(0, snap_down(start - window - lead))
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
            magnitude = TRIPLE_TILT_MAGNITUDE if dirsign < 0 else -TRIPLE_TILT_MAGNITUDE
            ramp.append((p.tick, "0"))
            ramp.append((p.tick + span, "%d" % magnitude))
            restore.append((p.tick + span, "0"))
            restore.append((p.tick + span + 1, "normal"))
            spans.append((p.tick, p.tick + span))
    return ramp, restore, spans


def compute_tilt_events(chart, pretilt_fix=False, min_factor=PRETILT_MIN_FACTOR):
    manual = chart.camera["tilt"]
    manual_ranges = [(s.tick, s.end_tick) for s in manual]

    points = [(0, "normal")]
    for seg in manual:
        points.append((seg.tick, fmt_tilt(TILT_VOX_TO_KSH * seg.start)))
        points.append((seg.end_tick, fmt_tilt(TILT_VOX_TO_KSH * seg.end)))

    if pretilt_fix:
        for (open_tick, close_tick) in _pretilt_brackets(chart, min_factor=min_factor):
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

    placed = _dedupe_consecutive(_place_track(points))

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
    return _dedupe_consecutive(combined)


def _dedupe_consecutive(items):
    n = len(items)
    out = []
    for i, (t, v) in enumerate(items):
        prev_v = items[i - 1][1] if i > 0 else None
        next_v = items[i + 1][1] if i + 1 < n else None
        if v != prev_v or v != next_v:
            out.append((t, v))
    return out


ROTX_TO_ZOOM_TOP = 140.0
RADI_TO_ZOOM_BOTTOM = -125.0


def compute_zoom_events(chart, rotx_scale=ROTX_TO_ZOOM_TOP, radi_scale=RADI_TO_ZOOM_BOTTOM):
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


SWING_ROLL_TYPES = (5, 7)

TRIPLE_ROLL_TYPE = 4

TRIPLE_TILT_MAGNITUDE = 72

TRIPLE_BEAT_TO_KSH192 = 48

DEFAULT_BEATS = {1: 6, 2: 2, 3: 3, 4: 12, 5: 3, 6: 7, 7: 3}

BEAT_TO_KSH192 = 24

TYPE67_UNIT_TO_KSH192 = 3


def _outgoing_dirsign(lst, i, max_lookahead=5):
    base = lst[i].pos
    for j in range(i + 1, min(i + 1 + max_lookahead, len(lst))):
        if lst[j].pos != base:
            return (lst[j].pos > base) - (lst[j].pos < base)
    return None


def _spin_length(chart, p):
    if p.roll_type == TRIPLE_ROLL_TYPE:
        length = triple_declared_beats(p) * TRIPLE_BEAT_TO_KSH192
    elif p.roll_type in (6, 7):
        length = (p.roll_length * TYPE67_UNIT_TO_KSH192 if p.roll_length
                  else DEFAULT_BEATS[p.roll_type] * BEAT_TO_KSH192)
    elif p.roll_length:
        length = p.roll_length * BEAT_TO_KSH192
    else:
        length = DEFAULT_BEATS.get(p.roll_type, 3) * BEAT_TO_KSH192
    return max(1, int(round(length)))


def triple_declared_beats(p):
    return p.roll_length if p.roll_length else DEFAULT_BEATS[TRIPLE_ROLL_TYPE]


def compute_spin_tokens(chart):
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
