"""Dumps a vtable, resolving each slot to its function and section.

    python dump_vtable.py <VA> [count]
"""
import os, sys, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pe_loader import Bin
from pdata_funcs import Funcs

b = Bin(); F = Funcs(b)
va = int(sys.argv[1], 16)
n = int(sys.argv[2]) if len(sys.argv) > 2 else 32
for i in range(n):
    p = va + 8*i
    d = b.read(p, 8)
    if not d: break
    t = struct.unpack('<Q', d)[0]
    sec = b.sec_of_va(t)
    fn = F.func_of(t)
    print("%3d  %x -> %-14x %-8s %s" % (i, p, t, sec['name'] if sec else '?',
          ("func %x-%x size=%x" % (fn[0], fn[1], fn[1]-fn[0])) if fn else ''))
    if not sec:
        break
