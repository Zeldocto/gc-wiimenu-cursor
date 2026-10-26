"""Find dead code ranges in the menu DOL (code-cave candidates).

Every address that anything can reach is collected: branch targets (b/bl/bc), raw
32-bit pointers anywhere in the DOL, and lis+addi/ori pairs. A dead range starts at an
unreferenced `stwu r1` prologue and ends just before the next reachable address or the
next prologue. Branches *inside* the range don't count.

  python tools/caves.py [--menu 514] [count]
"""
import sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
from ppc import menu_arg

LO, HI = 0x81330000, 0x816DFFE0


def targets(d):
    words = list(d.words())
    t, lis = {}, {}
    for a, w in words:
        op = w >> 26
        dst = None
        if op == 18:
            li = w & 0x03FFFFFC
            if li & 0x02000000: li -= 0x04000000
            dst = (a + li) & 0xFFFFFFFF
        elif op == 16:
            bd = w & 0xFFFC
            if bd & 0x8000: bd -= 0x10000
            dst = (a + bd) & 0xFFFFFFFF
        if dst is not None:
            t.setdefault(dst, []).append(a)
        t.setdefault(w & 0xFFFFFFFC, []).append(a)
        if op == 15 and (w >> 16) & 31 == 0:
            lis[(w >> 21) & 31] = ((w & 0xFFFF) << 16, a)
        elif op in (14, 24) and (w >> 16) & 31 in lis:
            hi, la = lis[(w >> 16) & 31]
            if a - la < 64:
                lo = w & 0xFFFF
                if op == 14 and lo & 0x8000: lo -= 0x10000
                t.setdefault((hi + lo) & 0xFFFFFFFC, []).append(a)
    return words, t


def dead_ranges(d):
    words, t = targets(d)
    wmap = dict(words)
    out = []
    for a, w in words:
        if not (LO <= a < HI and w >> 16 == 0x9421) or a in t:
            continue
        # the compiler can schedule instructions before the stwu (e.g. v513 0x815469B4 is
        # "cmpwi; stwu"), so the function really starts after the previous blr/b
        s = a - 4
        while wmap.get(s, 0x4E800020) != 0x4E800020 and wmap[s] >> 26 != 18:
            s -= 4
        if any(p in t for p in range(s + 4, a, 4)):
            continue
        e = a + 4
        while e < HI and wmap.get(e, 0) >> 16 != 0x9421:
            refs = [r for r in t.get(e, []) if not a <= r < e]
            if refs:
                break
            e += 4
        # trim back to the last blr so we don't swallow a following stub
        last = e - 4
        while last > a and wmap[last] != 0x4E800020:
            last -= 4
        if last > a:
            out.append((a, last + 4 - a))
    return sorted(out, key=lambda x: -x[1])


if __name__ == "__main__":
    argv = sys.argv[1:]
    d = menu_arg(argv)
    for s, n in dead_ranges(d)[:int(argv[0]) if argv else 20]:
        print(f"  {s:08x}-{s+n:08x}  size {n:#6x}")
