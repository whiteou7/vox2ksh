import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pe import Bin
from funcs import fmt

b = Bin()
start = int(sys.argv[1], 16)
end = int(sys.argv[2], 16)
o = b.va2off(start)
ins = list(b.md.disasm(b.data[o:o + (end - start)], start))
print(fmt(b, ins))
