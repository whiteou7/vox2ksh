#!/usr/bin/env python3
"""Parser for .vox charts (formats 10, 12 and 13). Camera control tracks end up in VoxChart.camera, and laser points expose roll_type, roll_length, cells_per_chain and unknown_c8, resolved per format version.
"""

import os

DEFAULT_BEAT_RESOLUTION = 48


def read_sections(path):
    txt = open(path, "r", encoding="cp932", errors="replace").read()
    out, cur = {}, None
    for line in txt.splitlines():
        ls = line.strip()
        if ls.startswith("//"):
            continue
        token = ls.split("//", 1)[0].strip()
        if token == "#END":
            cur = None
            continue
        if ls.startswith("#"):
            cur = ls
            out.setdefault(cur, [])
            continue
        if cur is not None and ls:
            out[cur].append(ls)
    return out


def parse_pos(s):
    m, b, t = (int(x) for x in s.split(","))
    return (m - 1, b - 1, t)


def parse_commasep(line):
    parts = [p.strip() for p in line.split(",") if p.strip() != ""]
    return [float(p) for p in parts]


class Timeline:
    def __init__(self, sec, res=DEFAULT_BEAT_RESOLUTION):
        self.res = res

        self.beats = []
        for line in sec.get("#BEAT INFO", []):
            f = line.split()
            mm = parse_pos(f[0])[0]
            self.beats.append((mm, int(f[1]), int(f[2])))
        if not self.beats:
            self.beats = [(0, 4, 4)]
        self.beats.sort()

        self.bpms = []
        for line in sec.get("#BPM INFO", []):
            f = line.split()
            mm, bb, tt = parse_pos(f[0])
            self.bpms.append((mm, bb, tt, float(f[1])))
        if not self.bpms:
            self.bpms = [(0, 0, 0, 120.0)]
        self.bpms.sort()

        self._measure_tick = {}
        self._measure_len = {}
        self._measure_cpb = {}
        acc, mi = 0, 0
        for meas in range(0, 4000):
            while mi + 1 < len(self.beats) and self.beats[mi + 1][0] <= meas:
                mi += 1
            self._measure_tick[meas] = acc
            num, den = self.beats[mi][1], self.beats[mi][2]
            cpb = int(round((4.0 / den) * self.res))
            self._measure_cpb[meas] = cpb
            length = num * cpb
            self._measure_len[meas] = length
            acc += length
        self._last_measure_tick = acc

        self._bpm_pts = []
        for (mm, bb, tt, bpm) in self.bpms:
            self._bpm_pts.append((self.abs_tick(mm, bb, tt), bpm))
        self._bpm_pts.sort()
        self._bpm_sec = [0.0]
        for i in range(1, len(self._bpm_pts)):
            dt = self._bpm_pts[i][0] - self._bpm_pts[i - 1][0]
            spb = 60.0 / self._bpm_pts[i - 1][1]
            self._bpm_sec.append(self._bpm_sec[-1] + dt / self.res * spb)

    def abs_tick(self, m0, b0, t):
        return self.measure_start_tick(m0) + b0 * self.cells_per_beat(m0) + t

    def tick_of(self, poss):
        return self.abs_tick(*parse_pos(poss))

    def measure_start_tick(self, measure0):
        if measure0 in self._measure_tick:
            return self._measure_tick[measure0]
        num, den = self.beats[-1][1], self.beats[-1][2]
        length = num * int(round((4.0 / den) * self.res))
        base_m = max(self._measure_tick)
        return self._measure_tick[base_m] + (measure0 - base_m) * length

    def measure_length(self, measure0):
        if measure0 in self._measure_len:
            return self._measure_len[measure0]
        num, den = self.beats[-1][1], self.beats[-1][2]
        return num * int(round((4.0 / den) * self.res))

    def cells_per_beat(self, measure0):
        if measure0 in self._measure_cpb:
            return self._measure_cpb[measure0]
        den = self.beats[-1][2]
        return int(round((4.0 / den) * self.res))

    def measure_of_tick(self, tick):
        meas = 0
        for m, tk in sorted(self._measure_tick.items()):
            if tk <= tick:
                meas = m
            else:
                break
        return meas, tick - self._measure_tick[meas]

    def timesig_at_measure(self, measure0):
        num, den = self.beats[0][1], self.beats[0][2]
        for (mm, n, d) in self.beats:
            if mm <= measure0:
                num, den = n, d
            else:
                break
        return num, den

    def bpm_at(self, tick):
        bpm = self._bpm_pts[0][1]
        for (tk, v) in self._bpm_pts:
            if tk <= tick:
                bpm = v
            else:
                break
        return bpm

    def beats_per_measure(self, tick):
        meas, _ = self.measure_of_tick(tick)
        num, den = self.timesig_at_measure(meas)
        return num * (4.0 / den)

    def seconds(self, tick):
        i = 0
        for k, (tk, _) in enumerate(self._bpm_pts):
            if tk <= tick:
                i = k
            else:
                break
        tk, bpm = self._bpm_pts[i]
        return self._bpm_sec[i] + (tick - tk) / self.res * (60.0 / bpm)


class ChipHold:
    __slots__ = ("tick", "length", "c2", "c3")

    def __init__(self, tick, length, c2=0, c3=None):
        self.tick = tick
        self.length = length
        self.c2 = c2
        self.c3 = c3

    @property
    def is_hold(self):
        return self.length > 0

    @property
    def end_tick(self):
        return self.tick + self.length


class LaserPoint:
    __slots__ = ("tick", "pos", "node_type", "roll_type", "effect",
                 "width", "curve_type", "roll_length", "cells_per_chain",
                 "unknown_c8")

    def __init__(self, tick, pos, node_type, roll_type, effect, width,
                 curve_type, roll_length, cells_per_chain, unknown_c8=0):
        self.tick = tick
        self.pos = pos
        self.node_type = node_type
        self.roll_type = roll_type
        self.effect = effect
        self.width = width
        self.curve_type = curve_type
        self.roll_length = roll_length
        self.cells_per_chain = cells_per_chain
        self.unknown_c8 = unknown_c8


def parse_bt_fx_track(sec, tag):
    out = []
    for line in sec.get(tag, []):
        f = line.split()
        if len(f) < 2:
            continue
        tick = _tick_from(f[0], sec)
        length = int(f[1])
        c2 = int(f[2]) if len(f) > 2 else 0
        c3 = int(f[3]) if len(f) > 3 else None
        out.append(ChipHold(tick, length, c2, c3))
    out.sort(key=lambda n: n.tick)
    return out


def parse_laser_track(sec, tag, version):
    out = []
    for line in sec.get(tag, []):
        f = line.split()
        if len(f) < 7:
            continue
        tick = _tick_from(f[0], sec)
        pos = float(f[1])
        if version < 12 or pos > 1.0:
            pos = pos / 127.0
        node_type = int(f[2])
        roll_type = int(f[3])
        effect = int(f[4])
        width = int(f[5])
        curve_type = int(f[7]) if len(f) > 7 else 0
        col = (lambda i: int(f[i]) if len(f) > i else None)
        if version >= 13:
            unknown_c8 = col(8) or 0
            roll_length = col(9) or 0
            cells_per_chain = col(10)
        else:
            unknown_c8 = 0
            roll_length = col(8) or 0
            cells_per_chain = col(9)
        out.append(LaserPoint(tick, pos, node_type, roll_type, effect, width,
                               curve_type, roll_length, cells_per_chain,
                               unknown_c8))
    out.sort(key=lambda p: p.tick)
    return out


def _tick_from(poss, sec):
    tl = sec.get("__timeline__")
    if tl is None:
        tl = Timeline(sec, sec.get("__res__", DEFAULT_BEAT_RESOLUTION))
        sec["__timeline__"] = tl
    return tl.tick_of(poss)


CAMERA_TAGS = ("Tilt", "CAM_RotX", "CAM_Radi")


class CameraSeg:
    __slots__ = ("tick", "length", "start", "end", "node_type")

    def __init__(self, tick, length, start, end, node_type):
        self.tick = tick
        self.length = length
        self.start = start
        self.end = end
        self.node_type = node_type

    @property
    def end_tick(self):
        return self.tick + self.length


def parse_spcontroler(sec, control_type):
    out = []
    for line in sec.get("#SPCONTROLER", []):
        f = line.split("\t")
        if len(f) < 6 or f[1] != control_type:
            continue
        tick = _tick_from(f[0], sec)
        length = int(float(f[3]))
        start = float(f[4])
        end = float(f[5])
        node_type = int(float(f[6])) if len(f) > 6 else 0
        out.append(CameraSeg(tick, length, start, end, node_type))
    out.sort(key=lambda s: s.tick)
    return out


BT_TAGS = ["#TRACK3", "#TRACK4", "#TRACK5", "#TRACK6"]
FX_TAGS = ["#TRACK2", "#TRACK7"]
LASER_TAGS = ["#TRACK1", "#TRACK8"]


class VoxChart:
    def __init__(self, path):
        self.path = path
        self.sec = read_sections(path)
        self.version = int((self.sec.get("#FORMAT VERSION") or ["10"])[0].strip())
        res_lines = self.sec.get("#BEAT RESOLUTION")
        self.res = int(res_lines[0].strip()) if res_lines else DEFAULT_BEAT_RESOLUTION
        self.sec["__res__"] = self.res
        self.tl = Timeline(self.sec, self.res)
        self.sec["__timeline__"] = self.tl

        self.bt = [parse_bt_fx_track(self.sec, t) for t in BT_TAGS]
        self.fx = [parse_bt_fx_track(self.sec, t) for t in FX_TAGS]
        self.laser = [parse_laser_track(self.sec, t, self.version) for t in LASER_TAGS]

        self.camera = {
            "tilt": parse_spcontroler(self.sec, "Tilt"),
            "cam_rotx": parse_spcontroler(self.sec, "CAM_RotX"),
            "cam_radi": parse_spcontroler(self.sec, "CAM_Radi"),
        }

        end = self.sec.get("#END POSITION")
        self.end_tick = self.tl.tick_of(end[0]) if end else self._infer_end_tick()

    def _infer_end_tick(self):
        last = 0
        for lst in self.bt + self.fx:
            for n in lst:
                last = max(last, n.end_tick)
        for lst in self.laser:
            for p in lst:
                last = max(last, p.tick)
        return last


def load(path):
    return VoxChart(path)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        raise SystemExit("usage: vox_parser.py <chart.vox>")
    c = load(sys.argv[1])
    print("version", c.version, "resolution", c.res, "end_tick", c.end_tick)
    for i, lst in enumerate(c.bt):
        print("BT-%s: %d notes" % ("ABCD"[i], len(lst)))
    for i, lst in enumerate(c.fx):
        print("FX-%s: %d notes" % ("LR"[i], len(lst)))
    for i, lst in enumerate(c.laser):
        print("laser-%s: %d points" % ("LR"[i], len(lst)))
    for name, lst in c.camera.items():
        print("%s: %d segments" % (name, len(lst)))
