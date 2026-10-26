"""Install / remove the hook in a running Dolphin (System Menu v513 or v514, detected from RAM).

  python tools/build.py && python tools/livepatch.py install
  python tools/livepatch.py remove
  python tools/livepatch.py status
  python tools/livepatch.py keep 30      # install, then re-install whenever boot code wipes it

After install/remove, clear Dolphin's JIT cache so it re-reads the code.
"""
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dolmem import Mem

BUILD = Path(__file__).resolve().parent.parent / "build"


def load_build(m):
    """-> (build dir, info) of the build whose call sites match the running menu."""
    for j in sorted(BUILD.glob("v*/gc_hook.json")):
        info = json.loads(j.read_text())
        if all(m.u32(s["addr"]) in (s["orig"], s["new"]) for s in info["sites"].values()):
            return j.parent, info
    raise SystemExit("the running menu matches no build in build/ (unsupported version, or not built?)")


def main(cmd, secs=30.0):
    m = Mem(write=True)
    out, info = load_build(m)
    print(f"menu v{info['menu']} ({info['name']})")
    sites = info["sites"]
    if cmd == "install":
        for addr, size in ((info["code_addr"], info["code_size"]), (info["data_addr"], info["data_size"])):
            if addr >= 0x81330000:  # cave inside the menu: must still hold the original dead code
                from ppc import Dol
                if m.read(addr, size) != Dol(info["menu"]).read(addr, size) and m.read(addr, 4) != (out / "gc_hook.bin").read_bytes()[:4]:
                    print(f"note: {addr:#x} differs from the DOL (already patched?)")
        for k, s in sites.items():
            cur = m.u32(s["addr"])
            if cur not in (s["orig"], s["new"]):
                raise SystemExit(f"{k}: unexpected word {cur:#010x} at {s['addr']:#x}; wrong menu version?")
        m.write(info["data_addr"], (out / "gc_data.bin").read_bytes())
        m.write(info["code_addr"], (out / "gc_hook.bin").read_bytes())
        for k, e in info.get("extra", {}).items():
            m.write(e["addr"], (out / f"gc_{k}.bin").read_bytes())
        for s in sites.values():
            m.write(s["addr"], struct.pack(">I", s["new"]))
    elif cmd == "keep":
        import time
        code, data = (out / "gc_hook.bin").read_bytes(), (out / "gc_data.bin").read_bytes()
        t0, last = time.time(), None
        while time.time() - t0 < secs:
            ev = []
            if m.read(info["code_addr"], len(code)) != code:
                m.write(info["code_addr"], code); ev.append("code")
            for k, e in info.get("extra", {}).items():
                blob = (out / f"gc_{k}.bin").read_bytes()
                if m.read(e["addr"], len(blob)) != blob:
                    m.write(e["addr"], blob); ev.append(k)
            if m.read(info["data_addr"] + 0x18, 8) != data[0x18:0x20]:   # MAGIC gone = data wiped
                m.write(info["data_addr"], data); ev.append("data")
            for k, s in sites.items():
                if m.u32(s["addr"]) == s["orig"]:
                    m.write(s["addr"], struct.pack(">I", s["new"])); ev.append(k)
            if ev:
                print(f"{time.time()-t0:6.2f}s wrote {' '.join(ev)}", flush=True)
            time.sleep(0.001)
    elif cmd == "remove":
        for s in sites.values():
            m.write(s["addr"], struct.pack(">I", s["orig"]))
    d = info["data_addr"]
    for k, s in sites.items():
        cur = m.u32(s["addr"])
        state = "HOOKED" if cur == s["new"] else "original" if cur == s["orig"] else "??"
        print(f"{k:5} {s['addr']:#x}: {cur:#010x} {state}")
    cx, cy = struct.unpack(">ff", m.read(d, 8))
    prev, rpt, ovr = struct.unpack(">III", m.read(d + 8, 12))
    pad = m.read(d + 0x40, 12)
    pcnt, kcnt = m.u32(d + 0x14), m.u32(d + 0x8C)
    print(f"hook calls: probe={pcnt} overridden frames={kcnt}")
    print(f"cursor=({cx:+.3f},{cy:+.3f}) buttons={prev:#06x} override={ovr} "
          f"GC port1: buttons={pad[0]<<8|pad[1]:#06x} stick=({struct.unpack('bb', pad[2:4])}) err={struct.unpack('b', pad[10:11])[0]}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "status", float(sys.argv[2]) if len(sys.argv) > 2 else 30.0)
