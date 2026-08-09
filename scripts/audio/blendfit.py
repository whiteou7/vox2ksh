"""Per effect region, fit beta in  |ref| ~= (1-beta)*|dry| + beta*|mine|.
   beta ~ 1 => my blend depth is right.  beta < 1 => I am over-applying.
   Also reports the overlap cases (FX+laser, FX-L+FX-R) which test chaining."""
import os, sys, numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, os.pardir, "shared"))
from _paths import WORK as SP, MUSIC
from metric import build_ref, spectrogram, rd, HOP
from apply_chart import read_sections, Timeline, parse_effects, FX_NAMES

FOLDER = os.path.join(MUSIC, "2229_kamui_tjhangneil")
refspec, nframes = build_ref()
dryspec = spectrogram(rd(os.path.join(SP, "kamui_dry.wav")), nframes)
minespec = spectrogram(rd(os.path.join(SP, "best.wav")), nframes)

sec = read_sections(os.path.join(FOLDER, "2229_kamui_tjhangneil_5m.vox"))
tl = Timeline(sec)
fxdefs = parse_effects(sec, "#FXBUTTON EFFECT INFO")

laser = np.zeros(nframes, bool)
peak = np.zeros(nframes, bool)
for trk in ("#TRACK1", "#TRACK8"):
    pts = []
    for line in sec.get(trk, []):
        f = line.split()
        if len(f) >= 9:
            pts.append((tl.tick_of(f[0]), int(f[2]), int(f[4])))
    pts.sort(key=lambda x: (x[0],))
    for i in range(len(pts) - 1):
        if pts[i][1] == 2 or pts[i+1][0] <= pts[i][0]:
            continue
        a = max(0, tl.samples(pts[i][0])//HOP); b = min(nframes, tl.samples(pts[i+1][0])//HOP+1)
        if pts[i][2] == 0:
            peak[a:b] = True
        else:
            laser[a:b] = True

fxmask = {}
occupied = np.zeros(nframes, int)
for trk in ("#TRACK2", "#TRACK7"):
    for line in sec.get(trk, []):
        f = line.split()
        if len(f) >= 3 and int(f[1]) > 0 and int(f[2]) >= 2:
            di = int(f[2]) - 2
            if di >= len(fxdefs):
                continue
            t0 = tl.tick_of(f[0])
            a = max(0, tl.samples(t0)//HOP); b = min(nframes, tl.samples(t0+int(f[1]))//HOP+1)
            occupied[a:b] += 1
            m = fxmask.setdefault(int(fxdefs[di][0]), np.zeros(nframes, bool))
            m[a:b] = True

act = (refspec.mean(axis=1) > 20) & (dryspec.mean(axis=1) > 20)


def beta(sel):
    if sel.sum() < 30:
        return None
    r = refspec[sel].ravel(); d = dryspec[sel].ravel(); m = minespec[sel].ravel()
    s = np.median(r) / max(np.median(d), 1e-9)          # level match
    r = r / s
    v = m - d
    den = float((v * v).sum())
    if den < 1e-9:
        return None
    return float(((r - d) * v).sum() / den), int(sel.sum())


print("beta = how much of my wet the capture actually contains (1.0 = correct depth)\n")
for t in sorted(fxmask):
    b = beta(fxmask[t] & act & ~laser & ~peak & (occupied == 1))
    if b:
        mixv = [e for e in fxdefs if int(e[0]) == t][0]
        print("  %-20s beta %5.2f   (n=%4d)  chart mix in row: %s"
              % (FX_NAMES.get(t, "?"), b[0], b[1],
                 ", ".join("%g" % x for x in mixv[1:4])))

print()
b = beta(peak & act & ~laser & (occupied == 0))
print("  %-20s beta %5.2f   (n=%4d)" % ("peak laser alone", b[0], b[1]))
b = beta(laser & act & (occupied == 0))
if b:
    print("  %-20s beta %5.2f   (n=%4d)" % ("tab laser alone", b[0], b[1]))
b = beta(act & (occupied >= 1) & (peak | laser))
if b:
    print("  %-20s beta %5.2f   (n=%4d)   <- FX and laser overlapping"
          % ("FX + laser", b[0], b[1]))
b = beta(act & (occupied >= 2))
if b:
    print("  %-20s beta %5.2f   (n=%4d)   <- two FX buttons at once"
          % ("FX-L + FX-R", b[0], b[1]))
