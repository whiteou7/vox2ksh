import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, os.pardir, os.pardir, os.pardir, "scripts", "shared"))
from game_paths import MUSIC, SCRIPTS, ensure_work
from match_references import REF, DIFF_SUFFIX, match_songs

sys.path.insert(0, os.path.join(SCRIPTS, "notes"))
import convert_notes as convert


def find_pairs():
    pairs = []
    for ref_name, folder in sorted(match_songs().items()):
        rd = os.path.join(REF, ref_name)
        for fn in sorted(os.listdir(rd)):
            base, ext = os.path.splitext(fn)
            if ext.lower() != ".ksh":
                continue
            suffix = DIFF_SUFFIX.get(base.lower())
            if suffix is None:
                continue
            vox_path = os.path.join(MUSIC, folder, "%s_%s.vox" % (folder, suffix))
            if os.path.exists(vox_path):
                pairs.append((vox_path, os.path.join(rd, fn), "%s/%s" % (ref_name, fn)))
    return pairs


class KshStats:
    def __init__(self, path):
        self.bt_chip = [0] * 4
        self.bt_hold = [0] * 4
        self.fx_chip = [0] * 2
        self.fx_hold = [0] * 2
        self.laser_points = [0] * 2
        self.laser_runs = [0] * 2
        self.bars = 0

        prev_bt = ["0"] * 4
        prev_fx = ["0"] * 2
        prev_laser = ["-"] * 2
        seen_body = False
        for raw in open(path, "r", encoding="utf-8-sig", errors="replace"):
            line = raw.strip()
            if not line or line.startswith("//") or line.startswith("#"):
                continue
            if line == "--":
                self.bars += 1
                seen_body = True
                continue
            m = re.match(r"^([012]{4})\|([012]{2})\|(.{2})", line)
            if not m:
                continue
            seen_body = True
            bt, fx, ls = m.group(1), m.group(2), m.group(3)
            for i, c in enumerate(bt):
                if c == "1":
                    self.bt_chip[i] += 1
                elif c == "2" and prev_bt[i] != "2":
                    self.bt_hold[i] += 1
                prev_bt[i] = c
            for i, c in enumerate(fx):
                if c == "2":
                    self.fx_chip[i] += 1
                elif c == "1" and prev_fx[i] != "1":
                    self.fx_hold[i] += 1
                prev_fx[i] = c
            for i, c in enumerate(ls):
                if c not in "-:":
                    self.laser_points[i] += 1
                    if prev_laser[i] == "-":
                        self.laser_runs[i] += 1
                prev_laser[i] = c
        if not seen_body:
            raise ValueError("no chart body found in %s" % path)


CATEGORIES = [
    ("bars", lambda s: [s.bars]),
    ("BT chip", lambda s: s.bt_chip),
    ("BT hold", lambda s: s.bt_hold),
    ("FX chip", lambda s: s.fx_chip),
    ("FX hold", lambda s: s.fx_hold),
    ("laser runs", lambda s: s.laser_runs),
    ("laser points", lambda s: s.laser_points),
]


def convert_and_count(vox_path, ksh_path, out_path):
    convert.convert(vox_path, out_path)
    return KshStats(out_path), KshStats(ksh_path)
