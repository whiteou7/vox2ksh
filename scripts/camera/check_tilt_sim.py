#!/usr/bin/env python3
"""Self-check for camera_events.simulated_tilt_points (specs/camera.md, "Simulated tilt"). Run it directly; it prints "ok" or fails an assert.
"""
import os
import random
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "shared"))
sys.path.insert(0, HERE)
import camera_events as ce  # noqa: E402
import vox_parser  # noqa: E402

# 120 BPM, so a measure is 2 s. A left laser rests on the right edge in measures 1 to 4,
# and a single manual Tilt of -0.5 holds through measures 6 and 7.
CHART = """#FORMAT VERSION
12
#END
#BEAT INFO
001,01,00\t4\t4
#END
#BPM INFO
001,01,00\t120.00\t4
#END
#TILT MODE INFO
001,01,00\t%d
#END
#END POSITION
010,01,00
#END
#TRACK1
001,01,00\t1.000000\t1\t0\t0\t1\t0\t0\t0
005,01,00\t1.000000\t2\t0\t0\t1\t0\t0\t0
#END
#SPCONTROLER
006,01,00\tTilt\t2\t384\t-0.50\t-0.50\t1.00\t0.00
#END
"""


def tilt_at(mode, measure):
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "check.vox")
        with open(path, "w", encoding="cp932") as f:
            f.write(CHART % mode)
        points = [(t, float(v)) for (t, v) in ce.compute_tilt_events(vox_parser.load(path), simulate=True)]
    return ce._interpolate(points, (measure - 1) * 192)


def main():
    random.seed(1)
    samples, y = [], 0.0
    for x in range(2000):
        y += random.uniform(-0.05, 0.05)
        samples.append((x, y))
    line = ce._swing_door(samples, ce.SIM_TOLERANCE)
    assert len(line) < len(samples) and all(abs(ce._interpolate(line, x) - y) <= ce.SIM_TOLERANCE + 1e-9 for x, y in samples)

    rows = [vox_parser.CameraSeg(tick, 10, value, value + 0.5, node)
            for tick, value, node in [(0, 0.005, 1), (100, 0.1, 2), (110, 0.2, 0), (120, 0.3, 1), (130, 0.4, 3), (200, 0.9, 3)]]
    assert ce._manual_tilt_series(rows) == [[(0, 0.0), (10, 0.505)], [(100, 0.1), (110, 0.2), (120, 0.3), (130, 0.4), (140, 0.9)]]

    # Mode 0: a full-right left laser is 10 degrees (ksh 1.0), manual -0.5 is -0.5 * -2.375. Mode 1 scales the laser by 2.375 and leaves manual alone.
    assert abs(tilt_at(0, 3) - 1.0) < 0.01 and abs(tilt_at(0, 7) - 1.1875) < 0.01
    assert abs(tilt_at(1, 3) - 2.375) < 0.01 and abs(tilt_at(1, 7) - 1.1875) < 0.01
    print("ok")


if __name__ == "__main__":
    main()
