"""Recover immediate integer/float arguments at every call site of given targets.

Unlike tools/playargs.py this does not linear-sweep .text (which desyncs on data
in code); it finds call sites via the RIP-relative scanner and then disassembles
only the containing function, from its .pdata start.

    python callargs.py <targetVA> [<targetVA> ...]
"""
import os, sys, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pe import Bin
from funcs import Funcs
from xref import scan_rip_refs
import capstone

ARG = [  # (index, integer regs, xmm reg)
    (1, {'ecx', 'rcx', 'cx', 'cl'}, 'xmm0'),
    (2, {'edx', 'rdx', 'dx', 'dl'}, 'xmm1'),
    (3, {'r8d', 'r8', 'r8w', 'r8b'}, 'xmm2'),
    (4, {'r9d', 'r9', 'r9w', 'r9b'}, 'xmm3'),
]


def scan_func(b, lo, hi):
    off = b.va2off(lo)
    out = []
    for ins in b.md.disasm(b.data[off:off + (hi - lo)], lo):
        out.append(ins)
    return out


def resolve(insns, idx, regs, xmm):
    """Walk backwards from insns[idx] to the previous call, tracking regs."""
    val = None
    for k in range(idx - 1, -1, -1):
        ins = insns[k]
        if ins.mnemonic == 'call':
            break
        parts = ins.op_str.split(',')
        dst = parts[0].strip()
        if dst in regs:
            if ins.mnemonic == 'xor' and parts[1].strip() == dst:
                return 0
            if ins.mnemonic == 'mov' and parts[1].strip().startswith('0x'):
                return int(parts[1].strip(), 16)
            if ins.mnemonic == 'mov' and parts[1].strip().isdigit():
                return int(parts[1].strip())
            if ins.mnemonic == 'lea':
                m = parts[1].strip()
                # lea edx, [r9 + 7]  with r9 zeroed just above
                if '+' in m and m.endswith(']'):
                    base = m[1:m.index('+')].strip()
                    disp = m[m.index('+') + 1:-1].strip()
                    try:
                        d = int(disp, 0)
                    except ValueError:
                        return None
                    for j in range(k - 1, -1, -1):
                        p2 = insns[j]
                        if p2.mnemonic == 'call':
                            break
                        if p2.op_str.split(',')[0].strip() == base:
                            if p2.mnemonic == 'xor' and p2.op_str.split(',')[1].strip() == base:
                                return d
                            break
                    return None
            return None
        if dst == xmm:
            return None
    return val


def main(targets):
    b = Bin(); F = Funcs(b)
    res = scan_rip_refs(b, targets, secnames=('.text',))
    for t in targets:
        print('=== target %x : %d refs' % (t, len(res[t])))
        for r in res[t]:
            fn = F.func_of(r)
            if not fn:
                print('   ref %x  (outside any .pdata function)' % r)
                continue
            insns = scan_func(b, fn[0], fn[1])
            hit = None
            for i, ins in enumerate(insns):
                if ins.mnemonic == 'call' and ins.op_str.startswith('0x') \
                        and int(ins.op_str, 16) == t:
                    if ins.address + 1 == r:
                        hit = i
                        break
            if hit is None:
                print('   ref %x  in %x  (call not recovered - disasm desync)'
                      % (r, fn[0]))
                continue
            args = [resolve(insns, hit, regs, xm) for (_i, regs, xm) in ARG]
            print('   call at %x in %x : rcx=%s rdx=%s r8=%s r9=%s'
                  % (insns[hit].address, fn[0],
                     *[('%d' % a) if a is not None else '?' for a in args]))


if __name__ == '__main__':
    main([int(a, 16) for a in sys.argv[1:]])
