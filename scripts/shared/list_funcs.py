"""Lists .pdata function starts in an address window.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pe_loader import Bin
from pdata_funcs import Funcs

lo = int(sys.argv[1], 16); hi = int(sys.argv[2], 16)
b = Bin(); F = Funcs(b)
for (st, en, uw) in F.entries:
    if lo <= st < hi:
        print("%x" % st)
