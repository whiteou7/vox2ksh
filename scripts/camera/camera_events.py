#!/usr/bin/env python3
"""Tilt, zoom and spin conversion (specs/camera.md): compute_tilt_events, compute_zoom_events and compute_spin_tokens. Pure functions over a loaded VoxChart, no file I/O.
"""
import bisect
import math
import sys


def format_tilt(v):
    s = "%.3f" % v
    s = s.rstrip("0").rstrip(".")
    if s in ("", "-0", "-"):
        return "0"
    return s


# The game's manual factor (Game::AngleUpdater): a vox unit is 23.75 degrees, a ksh unit 10.
TILT_VOX_TO_KSH = -2.375


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


def _triple_spin_ramps(chart):
    """(start tick, end tick, magnitude) of each roll_type 4 tilt ramp."""
    out = []
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
            out.append((point.tick, point.tick + span, magnitude))
    return out


def _triple_spin_tilt_points(chart):
    ramp, restore, spans = [], [], []
    for (start, end, magnitude) in _triple_spin_ramps(chart):
        ramp.append((start, "0"))
        ramp.append((end, "%d" % magnitude))
        restore.append((end, "0"))
        restore.append((end + 1, "normal"))
        spans.append((start, end))
    return ramp, restore, spans


# NABLA Game::AngleUpdater (specs/camera.md, "Simulated tilt"). Rates are per millisecond of real time.
TILT_EPS = 1.0 / 127
LASER_TILT_RATE = 0.00375
RELAX_TILT_RATE = 0.0009375
MANUAL_RATE_SCALE = 2.0
TILT_MODE_GAIN = 2.375
TILT_MODE_RATE = 0.09
KSH_TILT_DEGREES = 10.0
SIM_TOLERANCE = 0.005
SIM_SETTLE_MS = 10000


def _laser_sections(points):
    sections, current = [], None
    for point in points:
        if point.node_type == 1 or current is None:
            current = []
            sections.append(current)
        current.append(point)
        if point.node_type == 2:
            current = None
    return sections


def _manual_tilt_series(segs):
    """Point lists of the manual Tilt series, built as the game's series builder does."""
    def value(v):
        return 0.0 if abs(v) <= 0.01 else v

    out, index = [], 0
    while index < len(segs):
        seg = segs[index]
        index += 1
        if seg.node_type == 1:
            out.append([(seg.tick, value(seg.start)), (seg.end_tick, value(seg.end))])
        elif seg.node_type in (0, 2):
            series = [(seg.tick, value(seg.start))]
            while seg.node_type != 3 and index < len(segs):
                seg = segs[index]
                index += 1
                series.append((seg.tick, value(seg.start)))
            if seg.node_type == 3:
                series.append((seg.end_tick, value(seg.end)))
            out.append(series)
    return [series for series in out if len(series) >= 2]


def _linear_samples(times, values, stop):
    """(ms, value) of a piecewise-linear graph at each whole millisecond in [times[0], min(times[-1], stop))."""
    j, last = 0, len(times) - 1
    for k in range(math.ceil(times[0]), math.ceil(min(times[-1], stop))):
        while j + 1 < last and times[j + 1] <= k:
            j += 1
        t0, t1 = times[j], times[j + 1]
        yield k, (values[j + 1] if t1 <= t0 else values[j] + (values[j + 1] - values[j]) * (k - t0) / (t1 - t0))


def _simulate_lane_roll(chart, ms):
    """Filtered lane tilt in degrees at each millisecond, until it stops moving after the last event."""
    lasers = []
    for lane, points in enumerate(chart.laser):
        for section in _laser_sections(points):
            lasers.append(([ms(p.tick) for p in section], [p.pos if lane == 0 else p.pos - 1.0 for p in section]))
    series = [([ms(tick) for tick, _v in s], [v for _t, v in s]) for s in _manual_tilt_series(chart.camera["tilt"])]
    modes = [(ms(tick), mode) for tick, mode in chart.camera["tilt_mode"]]
    last_event = max([0.0] + [times[-1] for times, _v in lasers + series] + [t for t, _m in modes])
    count = int(last_event) + SIM_SETTLE_MS

    laser_target = [0.0] * count
    for times, values in lasers:
        for k, v in _linear_samples(times, values, count):
            laser_target[k] += v
    manual_target = [None] * count
    for i, (times, values) in enumerate(series):
        # A later series replaces the running one.
        stop = series[i + 1][0][0] if i + 1 < len(series) else count
        for k, v in _linear_samples(times, values, stop):
            manual_target[k] = v

    out = []
    s = o = 0.0
    mode, state, lock = 0, "pass", 0
    mode_index = 0
    for k in range(count):
        while mode_index < len(modes) and modes[mode_index][0] <= k:
            new_mode = modes[mode_index][1]
            mode_index += 1
            if new_mode == 0:
                if mode != 0:
                    state = "return"
            elif new_mode in (1, 2):
                mode, state, lock = new_mode, "follow" if new_mode == 1 else "ratchet", 0

        manual = manual_target[k]
        if manual is None:
            target, rate_scale = laser_target[k], 1.0
        else:
            target, rate_scale = manual * (TILT_VOX_TO_KSH if mode == 0 else -1.0), MANUAL_RATE_SCALE
        previous_s, previous_o = s, o
        if abs(target) >= TILT_EPS:
            step = LASER_TILT_RATE * rate_scale
            s = min(s + step, target) if target > s else max(s - step, target)
        elif abs(s) >= TILT_EPS:
            step = min(RELAX_TILT_RATE * rate_scale, abs(s) / 15.0 + TILT_EPS)
            s += -step if target < s else step
        else:
            s = 0.0

        d = KSH_TILT_DEGREES * s
        if state == "pass":
            o = d
        elif state == "return":
            o = min(o + TILT_MODE_RATE, d) if d > o else max(o - TILT_MODE_RATE, d)
            if abs(o - d) < TILT_EPS:
                mode, state = 0, "pass"
        else:
            goal = TILT_MODE_GAIN * d
            if state == "ratchet" and lock == 0:
                lock = 1 if d > TILT_EPS else -1 if d < -TILT_EPS else 0
            if state == "follow":
                o = min(o + TILT_MODE_RATE, goal) if goal > o else max(o - TILT_MODE_RATE, goal)
            elif lock > 0:
                o = max(o, min(o + TILT_MODE_RATE, goal))
            elif lock < 0:
                o = min(o, max(o - TILT_MODE_RATE, goal))
        out.append(o)
        if k > last_event and s == previous_s and o == previous_o:
            break
    return out


def _rotz_degrees(chart, ms):
    """BIL_RotZ as a function of milliseconds (each row is a linear graph, held after its end, until the next row), and the ticks where it jumps. at(t, before=True) is the value just before t."""
    graphs, jumps = [], set()

    def at(t, before=False):
        i = (bisect.bisect_left if before else bisect.bisect_right)(graphs, t, key=lambda g: g[0]) - 1
        if i < 0:
            return 0.0
        t0, t1, v0, v1 = graphs[i]
        return v1 if t >= t1 else v0 + (v1 - v0) * (t - t0) / (t1 - t0)

    for seg in chart.camera["bil_rotz"]:
        t0 = ms(seg.tick)
        graphs.append((t0, ms(seg.end_tick), seg.start if seg.c2 == 2 else at(t0), seg.end))
    for seg in chart.camera["bil_rotz"]:
        if at(ms(seg.tick)) != at(ms(seg.tick), before=True):
            jumps.add(seg.tick)
    return at, jumps


def _swing_door(samples, tolerance, start=None):
    """Few points whose linear interpolation stays within tolerance of every (x, y) sample, starting from `start` (at the first sample's x) if given."""
    ax, ay = start or samples[0]
    out = [(ax, ay)]
    lo, hi = -math.inf, math.inf
    px = ax
    for x, y in samples[1:]:
        dx = x - ax
        new_lo, new_hi = max(lo, (y - tolerance - ay) / dx), min(hi, (y + tolerance - ay) / dx)
        if new_lo > new_hi:
            ay += (lo + hi) / 2.0 * (px - ax)
            ax = px
            out.append((ax, ay))
            dx = x - ax
            new_lo, new_hi = (y - tolerance - ay) / dx, (y + tolerance - ay) / dx
        lo, hi = new_lo, new_hi
        px = x
    if px != ax:
        out.append((px, ay + (lo + hi) / 2.0 * (px - ax)))
    return out


def _interpolate(points, tick):
    i = bisect.bisect_right(points, tick, key=lambda p: p[0]) - 1
    if i < 0:
        return points[0][1]
    if i + 1 >= len(points):
        return points[-1][1]
    (t0, v0), (t1, v1) = points[i], points[i + 1]
    return v0 + (v1 - v0) * (tick - t0) / (t1 - t0)


def _add_spin_ramps(points, ramps):
    """Lays each roll_type 4 ramp on top of the simulated tilt, then drops back to it on the ramp's last tick."""
    for (start, end, magnitude) in ramps:
        # A tick can already hold two points (a BIL_RotZ jump): the ramp ends on the first and drops to the last.
        at_start = [p for p in points if p[0] == start] or [(start, _interpolate(points, start))]
        at_end = [p for p in points if p[0] == end] or [(end, _interpolate(points, end))]
        inside = [(t, v + magnitude * (t - start) / (end - start)) for (t, v) in points if start < t < end]
        points = ([p for p in points if p[0] < start] + at_start + inside
                  + [(end, at_end[0][1] + magnitude), (end, at_end[-1][1])] + [p for p in points if p[0] > end])
    return points


def simulated_tilt_points(chart):
    """(tick, ksh tilt) points reproducing NABLA's lane tilt, BIL_RotZ and type-4 ramps as manual tilt."""
    tl = chart.tl

    def ms(tick):
        return tl.seconds_at(tick) * 1000.0

    roll = _simulate_lane_roll(chart, ms)
    rotz, jumps = _rotz_degrees(chart, ms)
    step = max(1, chart.res // 48)
    end_ms = len(roll) - 1
    ticks = []
    while not ticks or (ms(ticks[-1]) < end_ms and ticks[-1] < chart.end_tick):
        ticks.append(len(ticks) * step)
    tempo_ticks = {tick for (tick, bpm), (_tick, previous) in zip(tl.bpm_pts[1:], tl.bpm_pts) if bpm != previous}
    # A BIL_RotZ jump splits the samples, so it becomes two tilt lines on one tick. A BPM change
    # ends a segment without a jump: USC interpolates in time and KSM in ticks, so they agree only within one tempo.
    runs, samples, joined = [], [], False
    for tick in sorted(set(ticks) | {t for t in jumps | tempo_ticks if t <= ticks[-1]}):
        t = ms(tick)
        k = max(0, min(int(t), end_ms - 1))
        o = roll[k] + (roll[min(k + 1, end_ms)] - roll[k]) * min(1.0, t - k)
        value = (o + rotz(t)) / KSH_TILT_DEGREES
        if samples and tick in jumps:
            samples.append((tick, (o + rotz(t, before=True)) / KSH_TILT_DEGREES))
            runs.append((samples, joined))
            samples, joined = [], False
        elif samples and tick in tempo_ticks:
            samples.append((tick, value))
            runs.append((samples, joined))
            samples, joined = [], True
        samples.append((tick, value))
    runs.append((samples, joined))
    points = []
    for run, joined in runs:
        if joined:
            points += _swing_door(run, SIM_TOLERANCE, start=points[-1])[1:]
        else:
            points += _swing_door(run, SIM_TOLERANCE)
    points = _add_spin_ramps(points, _triple_spin_ramps(chart))
    out = _collapse_equal_runs([(tick, format_tilt(v)) for (tick, v) in points])
    # USC applies manual tilt directly only if the first point after the switch to manual is an immediate change.
    # 0.001 is a hundredth of a degree.
    if len(out) > 1 and (len(out) < 3 or out[2][0] != out[1][0]):
        out.insert(2, (out[1][0], format_tilt(float(out[1][1]) + 0.001)))
    return out


def compute_tilt_events(chart, pretilt_fix=False, simulate=False):
    if simulate:
        return simulated_tilt_points(chart)
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
    argv = [a for a in sys.argv[1:] if a not in ("--pretilt-fix", "--simulate-tilt")]
    if not argv:
        raise SystemExit("usage: camera_events.py <chart.vox> [--pretilt-fix] [--simulate-tilt]")
    chart = voxmod.load(argv[0])
    tilt = compute_tilt_events(chart, pretilt_fix="--pretilt-fix" in sys.argv,
                               simulate="--simulate-tilt" in sys.argv)
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
