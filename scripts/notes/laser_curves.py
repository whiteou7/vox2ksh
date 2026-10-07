#!/usr/bin/env python3
"""Turns vox laser curves into discrete .ksh laser points, or with --ksh-version 2 into laser_l_curve/laser_r_curve beziers (specs/notes.md).
"""

import math

KSH_STEPS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmno"
N_STEPS = len(KSH_STEPS) - 1

RDP_TOL = 1.0 / 500

SLAM_GAP_FRAC = 32

KSH_SLAM_CUTOFF_FRAC = 32

MIN_RUN_GAP_TICKS = 2


def pos_to_char(pos):
    pos = 0.0 if pos < 0.0 else (1.0 if pos > 1.0 else pos)
    return KSH_STEPS[int(round(pos * N_STEPS))]


class Run:
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
    if len(pts) <= 2:
        return pts, (len(pts) == 2 and pts[1][0] - (pts[0][0] + lead) < min_gap)
    turns = [pts[i][0] for i in _direction_breaks(pts, CURVE_DEAD_ZONE)]
    turn_at = set(turns)
    out = [pts[0]]
    eff = [pts[0][0] + lead]
    dropped_after = {}
    for t, v in pts[1:-1]:
        if t in turn_at:
            while len(out) > 1 and out[-1][0] not in turn_at and t - eff[-1] < min_gap:
                dropped = dropped_after.pop(len(out) - 1, [])
                dropped_after.setdefault(len(out) - 2, []).extend([out.pop()] + dropped)
                eff.pop()
        elif any(0 < ta - t < min_gap for ta in turns):
            dropped_after.setdefault(len(out) - 1, []).append((t, v))
            continue
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
            continue
        rising = best_v > prev_v
        for t, v in cands:
            more_extreme = (rising and v >= best_v) or (not rising and v <= best_v)
            if (more_extreme and t - eff[i - 1] >= min_gap
                    and eff[i + 1] - t >= min_gap):
                best_t, best_v = t, v
        out[i] = (best_t, best_v)
        eff[i] = best_t

    if turn_at:
        out = _fill_between_turns(pts, out, eff, turn_at, min_gap)
    return out, tight


def _interp(pts, t):
    for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
        if t0 <= t <= t1:
            return v0 if t1 == t0 else v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return pts[-1][1]


def _fill_between_turns(pts, out, eff, turn_at, min_gap):
    fixed = [0] + [i for i in range(1, len(out) - 1) if out[i][0] in turn_at] + [len(out) - 1]
    ticks = [t for t, _v in pts]
    res = [out[0]]
    for a, b in zip(fixed, fixed[1:]):
        ta, tb = out[a][0], out[b][0]
        start, span = eff[a], tb - eff[a]
        k = span // min_gap - 1
        lo, hi = ticks.index(ta), ticks.index(tb)
        dense = all(y - x <= min_gap for x, y in zip(ticks[lo:hi], ticks[lo + 1:hi + 1]))
        if dense and k > b - a - 1:
            for j in range(1, k + 1):
                t = start + j * span // (k + 1)
                res.append((t, _interp(pts[lo:hi + 1], t)))
        else:
            res.extend(out[a + 1:b])
        res.append(out[b])
    return res


def decimate_segment(pts, min_gap, tol=RDP_TOL, lead=0):
    return _enforce_min_gap(_rdp(pts, tol), min_gap, lead)


def _split_into_runs(laser_points):
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
    nominal = start_t + max(1, gap)
    target = nominal
    if ceiling is not None:
        hard_limit = ceiling - 1
        if target > hard_limit:
            target = hard_limit
        soft_limit = ceiling - max(1, safe_gap)
        if target > soft_limit:
            target = max(soft_limit, nominal - max_backoff, start_t + 1)
            target = min(target, hard_limit)
    while target in used and target > start_t:
        target -= 1
    target = max(target, start_t + 1)
    used.add(target)
    return target


CURVE_FIT_TOL = 0.5 / N_STEPS

CURVE_MIN_GAIN = 0.25 / N_STEPS

CURVE_DEAD_ZONE = 0.5 / N_STEPS

CURVE_LEG_FRAC = 32


def _bezier_s(x, a):
    d = 1.0 - 2.0 * a
    if -1e-12 < d < 1e-12:
        return x
    disc = a * a + d * x
    return (math.sqrt(disc if disc > 0.0 else 0.0) - a) / d


def _score_a(a, xs, ys, scale):
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
    if fit is None:
        return None
    a, b, _rms, fit_max = fit
    if a == b or lin_max <= CURVE_FIT_TOL or lin_max - fit_max < CURVE_MIN_GAIN:
        return None
    return (a, b)


def _direction_breaks(pts, dead):
    breaks = []
    ext, direction = 0, 0
    for i in range(1, len(pts)):
        v, ev = pts[i][1], pts[ext][1]
        if direction == 0:
            if abs(v - ev) > dead:
                direction = 1 if v > ev else -1
                ext = i
        elif (v - ev) * direction > 0:
            ext = i
        elif (ev - v) * direction > dead:
            breaks.append(ext)
            direction = -direction
            ext = i
    return breaks


def _split_window(pts, lo, hi, min_gap, lead):
    first, last = lo + 1, hi - 1
    while first <= last and pts[first][0] - (pts[lo][0] + lead) < min_gap:
        first += 1
    while last >= first and pts[hi][0] - pts[last][0] < min_gap:
        last -= 1
    return first, last


def _fit_stretch(pts, lo, hi, min_gap, tol, lead=0, max_leg=None):
    sub = pts[lo:hi + 1]
    _lin_rms, lin_max = _line_error(sub)
    if lin_max <= tol:
        return [hi], [None]
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
            want = _inflection_index(sub, tol)
        if want is None:
            want = _worst_index(sub, fit)
        if want is not None:
            split = min(max(lo + want, first), last)
    if split is not None:
        li, lc = _fit_stretch(pts, lo, split, min_gap, tol, lead, max_leg)
        ri, rc = _fit_stretch(pts, split, hi, min_gap, tol, 0, max_leg)
        return li + ri, lc + rc
    return [hi], [_curve_or_none(fit, lin_max)]


def decimate_segment_curved(pts, min_gap, tol=CURVE_FIT_TOL, lead=0, max_leg=None):
    if max_leg is None:
        max_leg = max(1, min_gap * 24 // 32)
    if len(pts) <= 2:
        tight = len(pts) == 2 and pts[1][0] - (pts[0][0] + lead) < min_gap
        return list(pts), [None] * max(0, len(pts) - 1), tight
    idx, curves = _fit_stretch(pts, 0, len(pts) - 1, min_gap, tol, lead, max_leg)
    tight = pts[-1][0] - (pts[0][0] + lead) < min_gap
    return [pts[0]] + [pts[i] for i in idx], curves, tight


def build_runs(laser_points, tl, min_gap_frac=24, slam_gap_frac=SLAM_GAP_FRAC, curves=False):
    whole_note = 4 * tl.res
    min_gap = max(1, whole_note // min_gap_frac)
    used_ticks = set()
    out = []
    run_groups = [g for g in _split_into_runs(laser_points) if g]
    for gi, run_pts in enumerate(run_groups):
        width = run_pts[0].width
        segments = _split_at_slams(run_pts)

        next_true_start = run_groups[gi + 1][0].tick if gi + 1 < len(run_groups) else None

        flat, flat_curves, tight = [], [], False
        for si, seg in enumerate(segments):
            lead = 0 if si == 0 else (max(1, whole_note // slam_gap_frac) if slam_gap_frac else 1)
            if curves:
                kept, seg_curves, seg_tight = decimate_segment_curved(
                    seg, min_gap, lead=lead, max_leg=max(1, whole_note // CURVE_LEG_FRAC))
            else:
                kept, seg_tight = decimate_segment(seg, min_gap, lead=lead)
                seg_curves = [None] * max(0, len(kept) - 1)
            tight = tight or seg_tight
            if flat:
                flat_curves.append(None)
            flat.extend(kept)
            flat_curves.extend(seg_curves)

        points, slam_after = [], []
        for i, (t, v) in enumerate(flat):
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
                    safe_gap = max(1, whole_note // KSH_SLAM_CUTOFF_FRAC) + 1
                    t = _slam_landing_tick(points[-1][0], used_ticks, gap, ceiling, safe_gap)
                else:
                    t = _bump_to_free_tick(t, used_ticks)
            else:
                used_ticks.add(t)
            if points:
                slam_after.append(is_slam_landing)
            points.append((t, v))

        out.append(Run(points, slam_after, width, tight, flat_curves))

    _separate_runs(out)
    return out


def _separate_runs(runs):
    for i in range(len(runs) - 2, -1, -1):
        a, b = runs[i], runs[i + 1]
        visible_jump = pos_to_char(a.points[-1][1]) != pos_to_char(b.points[0][1])
        limit = b.start_tick - (MIN_RUN_GAP_TICKS if visible_jump else 1)
        if a.end_tick <= limit:
            continue
        if limit - (len(a.points) - 1) < 0:
            continue
        t = limit
        for j in range(len(a.points) - 1, -1, -1):
            tick, v = a.points[j]
            if tick <= t:
                break
            a.points[j] = (t, v)
            t -= 1
