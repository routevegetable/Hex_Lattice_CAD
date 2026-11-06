"""Rescale every saved `sparks.prob` from "how many LEDs" to a share of MAX_SPARKS.

Sparks used to read its `prob` slot as the number of LEDs lit at once: 15 for
about 15, 50 for about 50. A formula is now held to 0-1 where it is evaluated,
so a slot could never ask for more than about one. `prob` is now that count as
a share of MAX_SPARKS (100): 0.15 for about 15, 1 for 100.

Run from py/.  No argument lists what it would do, `--write` applies it, and
`--check` compares the presets on disk against the tarball beside this file.

    uv run python migrations/2026-11-05-sparks-prob-scale/migrate.py
    uv run python migrations/2026-11-05-sparks-prob-scale/migrate.py --write
    uv run python migrations/2026-11-05-sparks-prob-scale/migrate.py --check

One shot: it divides what is there by MAX_SPARKS, so running it twice would
divide twice.  `--write` with no file named therefore refuses once the tarball
exists.  Naming files - `--write presets/31.json` - migrates just those and is
for a preset that has been saved since, by an instrument still running the old
code.  Look at what it lists first: it cannot tell a value that has already been
migrated from one that has not.
"""

import json
import pathlib
import sys
import tarfile

MAX_SPARKS = 100  # what Sparks.MAX_SPARKS is: copied, as this is a record

HERE = pathlib.Path(__file__).parent
TARBALL = HERE / "presets-before.tar.gz"
PRESETS = sorted(pathlib.Path("presets").glob("*.json"))


def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def args_of(node):
    """The operands of an operation, in the new form or the old {a, b} one."""
    return list(node["args"]) if "args" in node else [node.get("a"), node.get("b")]


def with_operand(node, at, value):
    """The same operation with one operand replaced, in the form it was in."""
    out = dict(node)
    if "args" in out:
        out["args"] = [value if i == at else x for i, x in enumerate(out["args"])]
    else:
        out["ab"[at]] = value
    return out


def rescale(expr):
    """`expr` as it should read now, or None if it is not a shape this knows.

    A constant is divided by MAX_SPARKS. A product of a constant and anything
    else has the constant divided - and is dropped altogether if that leaves 1,
    since multiplying by 1 says nothing. The expression is not held to 0-1
    until it is an operation, and a constant is not held at all.
    """
    if is_number(expr):
        return round(expr / MAX_SPARKS, 10)

    if (
        isinstance(expr, dict)
        and expr.get("op") == "mul"
        and not expr.get("mod")
        and len(args_of(expr)) == 2
    ):
        operands = args_of(expr)
        numbers = [i for i, x in enumerate(operands) if is_number(x)]

        if len(numbers) == 1:
            at = numbers[0]
            factor = round(operands[at] / MAX_SPARKS, 10)
            return operands[1 - at] if factor == 1 else with_operand(expr, at, factor)

    return None


def show(x):
    if isinstance(x, dict):
        return f"{x['op']}({', '.join(show(a) for a in args_of(x))})"
    return repr(x)


def count(expr, x):
    """How many LEDs the slot asks for when the field in it reads `x`, as the
    old code read it (1) and as the new code does (MAX_SPARKS), or None for a
    shape this cannot evaluate. Every operation is held to 0-1; a constant is not."""

    def value(e):
        if is_number(e):
            return float(e)
        if isinstance(e, str):
            return x
        if isinstance(e, dict) and e.get("op") == "mul":
            a, b = (value(o) for o in args_of(e))
            return a * b
        raise ValueError(e)

    try:
        v = value(expr)
    except (ValueError, TypeError):
        return None
    return v if is_number(expr) else min(max(v, 0.0), 1.0)


def reads_alike(before, after):
    """Both read the same number of LEDs at a spread of field values - with the
    old slot taken as the count itself (unclamped, as it was meant) and the new
    one scaled by MAX_SPARKS."""
    for x in (0.0, 0.1, 0.25, 0.5, 0.99, 1.0):
        # The old formula was a count: nothing held it to 0-1 when it was written.
        def raw(e):
            if is_number(e):
                return float(e)
            if isinstance(e, str):
                return x
            a, b = (raw(o) for o in args_of(e))
            return a * b

        try:
            old = raw(before)
        except (ValueError, TypeError):
            return None
        new = count(after, x)
        if new is None:
            return None
        if abs(old - new * MAX_SPARKS) > 1e-6:
            return False
    return True


def formatted_as_written(text, data):
    """Whether `data` dumps back to exactly `text`: the instrument writes
    json.dumps(indent=2), and a file in that form can be changed in place
    without disturbing a line it does not mean to."""
    return json.dumps(data, indent=2) == text


def migrate(paths, write, named):
    changed = unknown = refused = 0

    if write and not named and TARBALL.exists():
        sys.exit(
            f"{TARBALL.name} exists, so this has been run: it would divide "
            "twice. Name the files to migrate: --write presets/31.json"
        )

    keep = []
    for path in paths:
        text = path.read_text()
        data = json.loads(text)
        expr = data.get("slots", {}).get("sparks.prob", "-")
        if expr == "-":
            continue

        new = rescale(expr)
        if new is None:
            unknown += 1
            print(
                f"!! {path.name}: sparks.prob = {show(expr)} - not a shape this "
                "knows, left alone. Change it by hand."
            )
            continue

        if new == expr:         # 0 stays 0: nothing to say and nothing to write
            continue

        ok = reads_alike(expr, new)
        flag = "" if ok else "   !! does NOT read the same (a factor over MAX_SPARKS?)"
        print(
            f"{path.name:9} ({data.get('name') or 'unnamed'})  "
            f"{show(expr)}  ->  {show(new)}{flag}"
        )

        if not formatted_as_written(text, data):
            refused += 1
            print("   !! not in the form the instrument writes; will not rewrite it")
            continue

        changed += 1
        keep.append((path, data, new))

    if write:
        if not named and not TARBALL.exists():
            with tarfile.open(TARBALL, "w:gz") as tar:
                for path in PRESETS:
                    tar.add(path, arcname=f"./py/{path.as_posix()}")
            print(f"\nkept every preset as it was in {TARBALL.name}")

        for path, data, new in keep:
            data["slots"]["sparks.prob"] = new
            path.write_text(json.dumps(data, indent=2))

    print(
        f"\n{changed} preset(s) {'rewritten' if write else 'would change'}, "
        f"{unknown} left alone for hand attention, {refused} refused"
    )


def check():
    """The presets as they are now against the tarball as they were: each
    sparks.prob has to ask for the same number of LEDs, and nothing else in any
    preset may have moved."""
    tar = tarfile.open(TARBALL)
    bad = rewritten = 0

    for path in PRESETS:
        was = json.load(tar.extractfile(f"./py/{path.as_posix()}"))
        now = json.loads(path.read_text())

        before, after = was["slots"].get("sparks.prob"), now["slots"].get("sparks.prob")
        if before is not None:
            same = reads_alike(before, after)
            if same is not True:
                bad += 1
                print(
                    f"!! {path.name}: {show(before)} -> {show(after)}"
                    + ("  (cannot evaluate)" if same is None else "  reads differently")
                )

        was["slots"].pop("sparks.prob", None)
        now["slots"].pop("sparks.prob", None)
        assert was == now, f"{path.name}: something other than sparks.prob changed"

        if before != after:
            rewritten += 1

    print(
        f"{len(PRESETS)} presets checked, {bad} read differently, {rewritten} rewritten"
    )


if __name__ == "__main__":
    named = [pathlib.Path(a) for a in sys.argv[1:] if not a.startswith("--")]
    if "--check" in sys.argv:
        check()
    else:
        migrate(named or PRESETS, "--write" in sys.argv, bool(named))
