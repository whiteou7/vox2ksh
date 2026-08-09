import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pe import Bin
from funcs import Funcs

lo = int(sys.argv[1], 16); hi = int(sys.argv[2], 16)
b = Bin(); F = Funcs(b)
for (st, en, uw) in F.entries:
    if lo <= st < hi:
        print("%x" % st)
