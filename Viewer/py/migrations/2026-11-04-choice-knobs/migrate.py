"""Move every saved knob position for a choice knob that used to be spread
over 0-127 onto the position that now means the same thing.

Run from py/.  `--write` applies it, no argument lists what it would do, and
`--check` compares the presets on disk against the tarball beside this file.

One shot: it reads a stored value as an old-layout position, so running it
twice would shift everything a second time.  It has been run - see README.md.
"""
import json
import pathlib
import sys
import tarfile

# Both layouts, written out rather than worked out from the live code: this is
# a record of one afternoon's change, and it has to keep meaning that however
# the lists grow afterwards.
MODES = ["straight", "bidirectional", "bidirectional-d", "bidirectional-d1",
         "bidirectional-d2", "bidirectional-h", "star"]
LAYOUTS = {
    # control: (what the knob read before, what it reads now)
    "rotary.parts":       ({0: "1", 32: "2", 64: "3", 95: "4", 127: "5"},
                           {i: str(i + 1) for i in range(5)}),
    "v_rotary.parts":     ({0: "1", 32: "2", 64: "3", 95: "4", 127: "5"},
                           {i: str(i + 1) for i in range(5)}),
    "loops.copies":       ({round(i * 127 / 15): str(i + 1) for i in range(16)},
                           {i: str(i + 1) for i in range(16)}),
    "random_lines.count": ({round(i * 127 / 10): str(i) for i in range(11)},
                           {i: str(i) for i in range(11)}),
    "trace_lines.mode":   ({round(i * 127 / 6): n for i, n in enumerate(MODES)},
                           dict(enumerate(MODES))),
}

# Where each of those sat on the desk unless a preset said otherwise.
DEFAULT = {"rotary.parts": 93, "v_rotary.parts": 93, "loops.copies": 104,
           "random_lines.count": 119, "trace_lines.mode": 120}

# A CC no control defaults to and no preset mentioned, for a knob that has to
# be given a place of its own.
SPARE = 94

HERE = pathlib.Path(__file__).parent
FILES = (sorted(pathlib.Path("presets").glob("*.json"))
         + [pathlib.Path("preset.json"), pathlib.Path("../preset.json")])

near = lambda items, v: items[min(items, key=lambda k: abs(k - v))]
back = lambda items, label: next(k for k, l in items.items() if l == label)


def live_fields(d):
    """Every field named by a slot of an effect that is switched on."""
    active, out = set(d.get("active", [])), set()

    def walk(x):
        if isinstance(x, str):
            out.add(x)
        elif isinstance(x, dict):
            walk(x.get("a"))
            walk(x.get("b"))

    for slot, expr in d.get("slots", {}).items():
        if slot.split(".")[0] in active:
            walk(expr)

    return out


def reads(d, which):
    """What each choice knob in a preset says, under layout 0 or 1."""
    out = {}
    for name, layouts in LAYOUTS.items():
        cc = d.get("cc_map", {}).get(name, DEFAULT[name])
        value = d.get("ccs", {}).get(str(cc))
        out[name] = None if value is None else near(layouts[which], value)
    return out


def migrate(write):
    touched = conflicts = 0

    for path in FILES:
        d = json.loads(path.read_text())
        ccs, cmap = d.get("ccs", {}), d.get("cc_map", {})
        at = lambda n: cmap.get(n, DEFAULT[n])
        live = live_fields(d)

        # Which choice knobs sit on each CC in this preset. More than one can:
        # rotary.parts and v_rotary.parts share a knob by default.
        on_cc: dict[int, list[str]] = {}
        for name in LAYOUTS:
            if str(at(name)) in ccs:
                on_cc.setdefault(at(name), []).append(name)

        notes = []
        for cc, names in sorted(on_cc.items()):
            was = ccs[str(cc)]
            wants = {n: back(LAYOUTS[n][1], near(LAYOUTS[n][0], was))
                     for n in names}

            if len(set(wants.values())) > 1:
                # Two choice knobs sharing one CC that used to read the same
                # position and now do not. The one with a cc_map entry was put
                # there on purpose, so it keeps the knob; whatever is only
                # there because its default landed on the same number moves to
                # a CC nothing else uses, at the position that keeps its
                # meaning. That costs it a place on the desk and keeps the
                # preset sounding the same, which is the point of the exercise.
                conflicts += 1
                stays = [n for n in names if n in cmap] or names[:1]
                moving = [n for n in names if n not in stays]
                assert len({wants[n] for n in stays}) == 1, (path.name, stays)
                assert len({wants[n] for n in moving}) == 1, (path.name, moving)

                print(f"!! {path.name} cc{cc} = {was}: two knobs in one place -")
                for name in names:
                    mark = " (live)" if name.split(".")[0] in live else ""
                    where = "keeps" if name in stays else f"moves to cc{SPARE}"
                    print(f"     {name} read"
                          f" {near(LAYOUTS[name][0], was)!r}{mark},"
                          f" now position {wants[name]} - {where}")

                ccs[str(cc)] = wants[stays[0]]
                ccs[str(SPARE)] = wants[moving[0]]
                for name in moving:
                    cmap[name] = SPARE

                notes.append(f"  cc{cc} {was:>3} -> {wants[stays[0]]:<3}"
                             f" {', '.join(stays)}"
                             f"   [{', '.join(moving)} moved to cc{SPARE}"
                             f" = {wants[moving[0]]}]")
                continue

            want = next(iter(wants.values()))
            if want == was:
                continue

            ccs[str(cc)] = want
            notes.append(f"  cc{cc} {was:>3} -> {want:<3} " + ", ".join(
                f"{n} = {near(LAYOUTS[n][0], was)!r}" for n in names))

        if notes:
            touched += 1
            print(f"{path.name}  ({d.get('name') or 'unnamed'})")
            print("\n".join(notes))
            if write:
                d["ccs"] = {k: ccs[k] for k in sorted(ccs, key=int)}
                path.write_text(json.dumps(d, indent=2))

    print(f"\n{touched} preset(s) {'rewritten' if write else 'would change'},"
          f" {conflicts} conflict(s)")


def check():
    """Every preset as it is now, against the tarball as it was: the knobs
    have to read the same, and nothing but their CC values may have moved."""
    tar = tarfile.open(HERE / "presets-before.tar.gz")
    stale = bad = 0

    for path in FILES:
        name = ("./preset.json" if path == pathlib.Path("../preset.json")
                else f"./py/{path.as_posix()}")
        was = json.load(tar.extractfile(name))
        now = json.loads(path.read_text())

        if reads(was, 0) != reads(now, 1):
            bad += 1
            print(f"!! {path.name} does not read the same:")
            for key, before in reads(was, 0).items():
                after = reads(now, 1)[key]
                if before != after:
                    print(f"     {key}: {before!r} -> {after!r}")

        for key in ("slots", "active", "muted", "name"):
            assert was.get(key) == now.get(key), (path.name, key)

        allowed = {str(was.get("cc_map", {}).get(n, DEFAULT[n]))
                   for n in LAYOUTS} | {str(SPARE)}
        moved = {k for k in set(was["ccs"]) | set(now["ccs"])
                 if was["ccs"].get(k) != now["ccs"].get(k)}
        assert moved <= allowed, (path.name, moved - allowed)

        if was != now:
            stale += 1

    print(f"{len(FILES)} presets checked, {bad} read differently,"
          f" {stale} rewritten")


if __name__ == "__main__":
    if "--check" in sys.argv:
        check()
    else:
        migrate("--write" in sys.argv)
