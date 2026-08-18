#!/usr/bin/env python3
"""
.vox -> .ksh, notes + camera together.

    python convert.py <chart.vox> [-o out.ksh]

Thin CLI: all the note-grid machinery lives in ../notes/convert.py, this
just calls it with camera=True so tilt/zoom_top/zoom_bottom option lines
and lane-spin tokens (computed in camera.py) get placed into the same grid.
See specs/camera.md for what's solid vs approximate in those values -
this script doesn't add any conversion logic of its own.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "notes"))
import convert as notes_convert


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vox", help="path to a .vox chart")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--pretilt-fix", action="store_true",
                    help="bracket laser sections KSM would tilt into early with "
                         "tilt=zero..tilt=normal, so the lane stays flat until the "
                         "laser actually arrives (see specs/camera.md)")
    args = ap.parse_args()
    out = args.output or os.path.splitext(os.path.basename(args.vox))[0] + ".ksh"
    path = notes_convert.convert(args.vox, out, camera=True,
                                 pretilt_fix=args.pretilt_fix)
    print("wrote %s" % path)


if __name__ == "__main__":
    main()
