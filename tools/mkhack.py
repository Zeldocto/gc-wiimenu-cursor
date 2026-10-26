"""Turn the built hooks into Priiloader hacks_hash.ini entries, one per menu version.

Every block has the same name; Priiloader only lists (and applies) the one whose
minversion/maxversion matches the console's menu, so one file covers 4.3U and 4.3E.

  python tools/build.py --release && python tools/mkhack.py hack/gc_cursor_hack.ini
  python tools/build.py && python tools/mkhack.py            -> build/gc_cursor_hack.ini (debug build)
  python tools/mkhack.py apply [file.ini]                    -> parse the .ini like Priiloader
                                                                and write the block for the running
                                                                menu into Dolphin RAM (boot it paused)
"""
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hackini import parse

BUILD = Path(__file__).resolve().parent.parent / "build"
OUT = BUILD / "gc_cursor_hack.ini"
NAME = "GameCube Controller Cursor"   # Priiloader shows at most 39 characters
RELEASE = "1.2"


def words(b):
    assert len(b) % 4 == 0
    return ",".join(f"0x{w:08X}" for w in struct.unpack(f">{len(b)//4}I", b))


def block(d):
    """-> (flags, lines) of the hack block for one build directory (all addresses are menu-specific)."""
    info = json.loads((d / "gc_hook.json").read_text())
    v = info["menu"]
    patches = [
        ("hook code (dead function)", info["code_addr"], (d / "gc_hook.bin").read_bytes()),
        ("hook data (dead function)", info["data_addr"], (d / "gc_data.bin").read_bytes()),
    ] + [(f"{k} (dead function)", e["addr"], (d / f"gc_{k}.bin").read_bytes())
         for k, e in info.get("extra", {}).items()]
    patches += [(f"bl {s['hook']} ({k} call site)", s["addr"], struct.pack(">I", s["new"]))
                for k, s in info["sites"].items()]
    build = "DEBUG build (" + ", ".join(info["flags"]) + ")" if info.get("flags") else "release"
    lines = [f"[{NAME}]", f"maxversion={v}", f"minversion={v}", f"amount={len(patches)}",
             f"#v{RELEASE} {build}, System Menu {info['name']} (v{v})",
             "#Stick moves the pointer, D-pad jumps between buttons, A/B/Start(HOME)/L(-)/R+Z(+)/X(1)/Y(2)"
             " when no Wii Remote is on"]
    for desc, addr, data in patches:
        lines += [f"#{desc}", f"offset=0x{addr:08X}", f"patch={words(data)}"]
    return info["flags"], lines


def make(out=OUT):
    blocks = [block(j.parent) for j in sorted(BUILD.glob("v*/gc_hook.json"))]
    assert blocks, "nothing built: run tools/build.py first"
    assert len({tuple(f) for f, _ in blocks}) == 1, "mixed release/debug builds: rerun tools/build.py"
    lines = [l for _, b in blocks for l in b + [""]][:-1]   # blank line between blocks
    text = "\n".join(lines) + "\n"
    assert max(len(l) for l in lines) < 0x2000, "line too long for Priiloader"
    Path(out).write_text(text, newline="\n")
    return text


def apply(path=OUT):
    from dolmem import Mem
    from livepatch import load_build
    from ppc import Dol
    m = Mem(write=True)
    menu = load_build(m)[1]["menu"]
    (hack,) = [h for h in parse(Path(path).read_text()) if h["min"] <= menu <= h["max"]]
    dol = Dol(menu)
    print(f"menu v{menu}")
    for p in hack["patches"]:   # same order as Priiloader's loader
        a, data = p["offset"], p["patch"]
        if m.read(a, len(data)) != dol.read(a, len(data)):
            raise SystemExit(f"RAM at {a:#x} isn't the stock menu (already patched, or not paused at boot?)")
    for p in hack["patches"]:
        m.write(p["offset"], p["patch"])
        print(f"wrote {len(p['patch']):#5x} bytes at {p['offset']:#x}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "apply":
        apply(sys.argv[2] if len(sys.argv) > 2 else OUT)
    else:
        out = sys.argv[1] if len(sys.argv) > 1 else OUT
        t = make(out)
        print(f"wrote {out} ({len(t)} bytes)")
        print("\n".join(l if len(l) < 110 else l[:100] + " ..." for l in t.splitlines()))
