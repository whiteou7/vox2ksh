#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", default=None, help="game install to copy the SE bank from "
                                                   "(default: scripts/shared/_paths.GAME)")
    ap.add_argument("--ffmpeg", default=None, help="ffmpeg.exe to bundle (default: auto-detect)")
    ap.add_argument("--skip-assets", action="store_true",
                     help="reuse whatever's already staged in gui/assets/ instead of "
                          "re-copying from --game/--ffmpeg")
    args = ap.parse_args()

    if not args.skip_assets:
        cmd = [sys.executable, os.path.join(HERE, "build_assets.py")]
        if args.game:
            cmd += ["--game", args.game]
        if args.ffmpeg:
            cmd += ["--ffmpeg", args.ffmpeg]
        subprocess.run(cmd, check=True)
        print()

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        raise SystemExit("pyinstaller isn't installed in this environment - "
                          "run: pip install pyinstaller")

    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm",
        "--distpath", os.path.join(HERE, "dist"),
        "--workpath", os.path.join(HERE, "work"),
        os.path.join(HERE, "vox2ksh_gui.spec"),
    ], check=True, cwd=ROOT)

    print()
    print("built: %s" % os.path.join(HERE, "dist", "vox2ksh.exe"))


if __name__ == "__main__":
    main()
