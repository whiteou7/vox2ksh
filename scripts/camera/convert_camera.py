#!/usr/bin/env python3
"""Converts a chart with camera events on, through convert_notes.convert(..., camera=True).

    python convert_camera.py <chart.vox> [-o out.ksh] [--pretilt-fix]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "notes"))
import convert_notes as notes_convert


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
