"""Survey every .vox chart: tabulate #FXBUTTON EFFECT INFO and #TAB EFFECT INFO rows
by leading effect-type id, so we can infer parameter layout and value ranges."""
import os, glob, collections, statistics, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import MUSIC as ROOT

def sections(path):
    try:
        txt = open(path, 'r', encoding='cp932', errors='replace').read()
    except Exception:
        return {}
    out = {}
    cur = None
    for line in txt.splitlines():
        ls = line.strip()
        if ls.startswith('#END'):
            cur = None; continue
        if ls.startswith('#'):
            cur = ls; out.setdefault(cur, []); continue
        if cur is not None and ls:
            out[cur].append(ls)
    return out

fx = collections.defaultdict(list)   # (type, ncols) -> rows
tab = collections.defaultdict(list)
fmtver = collections.Counter()
files = glob.glob(os.path.join(ROOT, '*', '*.vox'))
print("vox files:", len(files))

for p in files:
    s = sections(p)
    for v in s.get('#FORMAT VERSION', []):
        fmtver[v.strip()] += 1
    for key, bucket in (('#FXBUTTON EFFECT INFO', fx), ('#TAB EFFECT INFO', tab)):
        for line in s.get(key, []):
            parts = [x.strip() for x in line.split(',') if x.strip() != '']
            if not parts: continue
            try:
                vals = [float(x) for x in parts]
            except ValueError:
                continue
            if all(v == 0 for v in vals):
                continue
            t = int(vals[0])
            bucket[(t, len(vals))].append(vals)

print("\nFORMAT VERSION counts:", dict(fmtver))

def report(name, bucket):
    print("\n==== %s ====" % name)
    for (t, n) in sorted(bucket):
        rows = bucket[(t, n)]
        print("\n type=%d  ncols=%d   count=%d" % (t, n, len(rows)))
        for c in range(1, n):
            col = [r[c] for r in rows]
            uniq = sorted(set(col))
            desc = "min=%.4g max=%.4g nuniq=%d" % (min(col), max(col), len(uniq))
            if len(uniq) <= 12:
                desc += "  vals=" + ",".join("%g" % u for u in uniq)
            else:
                desc += "  ex=" + ",".join("%g" % u for u in uniq[:6]) + "..."
            print("   p%d: %s" % (c, desc))

report("FXBUTTON", fx)
report("TAB(laser)", tab)
