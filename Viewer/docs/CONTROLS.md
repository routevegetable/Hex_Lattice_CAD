# Control names: who owns what

A **control** is a knob or pad the instrument watches. Its **name** says what
it is for, and that name is the only thing that identifies it — not the CC
number it happens to be on. Getting a name wrong does not break rendering; it
breaks the desk, quietly, by putting a knob under the wrong thing or nowhere
at all.

See `docs/glossary.md` for Control, Comment, `MIDIFor`, Watched and Hidden.
This is the convention layer on top: who may own a control, how the name is
formed, and what the UI concludes from it.

## The shape of a name

```python
midi.for_("rotary").cc(KA5, "period", meta=FloatRange(500, 16000, "ms", geometric=True))
#          ^owner        ^default ^role
```

giving the name `rotary.period`. Always `owner.role`, one dot. The owner comes
from `midi.for_(...)`, the role from the `cc()` call, and the two are joined by
`MIDIFor` in `examples/midi.py`.

**The owner must equal the attribute name it is declared under.** This is a
convention, not something enforced, and it is load-bear: the UI finds the knobs
behind an expression by matching a slot's field and operator names against
these owners. `rotary = RotaryField(graph, midi.for_("rotary"), ...)` — if those
two strings disagree, the field renders perfectly and its knobs vanish from
the slot that uses it.

The one sanctioned exception is a **deliberately shared owner** — see below.

## Three kinds of owner

| Owner | Declared in | Example name |
|---|---|---|
| Field | `class FIELDS`, `instrument/fields.py` | `ripple.speed` |
| Operator | `class OPERATORS`, `instrument/fields.py` | `prob_zap.length` |
| Effect | `class EFFECTS`, `instrument/__main__.py` | `prob_zaps.length` |

A field is something a slot can be pointed at. An operator is something an
expression names in `{"op": ..., "args": [...]}`. An effect owns a control when
the control shapes how it *draws* rather than what drives it — `ProbZaps` keeps
its zap length on a knob for exactly that reason, and the comment on its class
says so.

All three reach the same `MIDI` object, so all three share one namespace of
names and one pool of CC numbers.

## The name is identity; the number is only where it starts

- `cc(default_id, ...)` says where a control *starts*. A preset's `cc_map`
  moves it, and `set_cc_map` puts anything the map leaves out back on its
  declared default.
- **Two things asking by the same name get the same control.** That is how the
  phase-shifted copies of an effect share one knob.
- **Two different names may sit on the same number.** Both end up on that
  knob's state and both read it, and a preset can later pull them apart.

Those last two are different tools, and picking the wrong one is the usual
mistake:

```python
# One control, shared. Neither object is named after it, so neither is
# separable from the other - they are the same knob by definition.
shared = midi.for_("gradient_1")
gradient_1_h = GradientChooser(True, shared, 82)
gradient_1_s = GradientChooser(False, shared, 82)

# Two controls that happen to start on the same knobs. Turning KA5 moves both,
# but a preset can give v_rotary.period a knob of its own.
rotary   = RotaryField(graph, midi.for_("rotary"),   period=KA5, parts=KA6, shape=KA7)
v_rotary = RotaryField(graph, midi.for_("v_rotary"), period=KA5, parts=KA6, shape=KA7)
```

Use the shared `MIDIFor` when the two things are two halves of one setting. Use
separate names when they are two settings that merely begin life together.

## What the UI does with the names

`controlsFor(tree)` in `static/mobile.js` and `static/v3.js` lists the knobs
behind an open slot, and the two kinds of owner a slot can reach are matched
differently:

- **A field matches exactly.** `random_lines` takes `random_lines.*` and
  nothing else.
- **An operator matches any name it carries as a prefix.** `gradient_1_h` takes
  `gradient_1.select`.

The asymmetry is not arbitrary. Several fields are named after another field
with something on the end — `random_lines` is not a kind of `random`,
`trace_lines` not a kind of `trace` — so matching fields loosely would hand
each of them the other's knobs. Operators need the loose rule because a shared
owner is named after none of the operators that use it.

**So: never name an operator after an existing field or operator plus a
suffix.** It would silently inherit that one's controls. Fields are free to do
it. There is a check for this worth running after adding an operator:

```
cd Viewer/py && uv run python -I -c "
import ast, pathlib
t = ast.parse(pathlib.Path('pylattice/instrument/fields.py').read_text())
def names(cls):
    for n in ast.walk(t):
        if isinstance(n, ast.ClassDef) and n.name == cls:
            return [g.id for s in n.body for g in getattr(s, 'targets', [])
                    if isinstance(g, ast.Name)]
    return []
f, o = set(names('FIELDS')), set(names('OPERATORS'))
print([(a, b) for a in o for b in f | o if a != b and a.startswith(b + '_')] or 'clear')
"
```

`opsIn` and `fieldsIn` are what walk the expression for those names.

**An effect's own controls are not behind any slot**, so they are found a
different way: `controlsOwnedBy(name)` takes every control named `name.*`,
exactly, like a field. Both pages show them with the effect rather than in a
slot - at the top of its slots in `mobile.js`, at the top of its card in
`v3.js` - and the controller map in `v3.js` counts them as in use while the
effect is in the chain and not muted, so they light up and "assign them" can
put them on the box.

**The faders go on the box's faders, in order.** `fader_a` to `fader_h` are F1 to
F8, which on the Akai are CCs 12-19. `v3.js` makes a new preset with that map, and
"assign them" puts a fader on its own fader first. The server already declares
`fader_c` to `fader_h` on 14-19, so only `fader_a` and `fader_b` - declared on
BeatStep knobs - need mapping. One thing to know: CCs 16-19 are also where the
BeatStep's `wipe2.speed`, `trace.speed`, `ripple2.speed` and `wipe1.speed` start,
so in a preset that maps nothing a fader there moves one of those as well.

`v3.js` has its own copies of all of this, following the same rules. `app.js` is
an older page that has not been kept up with any of it.

## Picking a CC number

CCs are declared in exactly two places: a literal handed to `midi.cc(...)`
inside a field, operator or effect, and the number `FIELDS`/`OPERATORS`/
`EFFECTS` passes in. Nowhere else.

As of this writing 50 are taken:

- **10, 16–19, 71–77, 79, 91, 93** — the sixteen BSP knobs, `KA1`–`KB8` in
  `instrument/hardware.py`. All spoken for; a new control here moves something
  that is already there.
- **20–55** — what the step buttons send. Nothing watches them, and
  `hardware.py` records them so nothing claims them by accident.
- **36–51** — the pads, as *notes*. A different space from CCs, but worth
  knowing before reading a number out of `hardware.py`. `PA1`–`PA6` and
  `PB1`–`PB8` are taken; `PA7` and `PA8` (50, 51) are free.
- **14, 15, 81–89, 102–125** — off the desk: declared, mapped in the UI, and
  reachable from a preset's `cc_map`.

Free CCs: **1–9, 11–13, 56–70, 78, 80, 90, 92, 94–101, 126–127**.

**Do not read free numbers off `/controls`.** `Console.controls()` only reports
a mapping whose CC has actually said something on the wire, so a declared knob
nobody has touched since boot is missing from it — 103, 105 and 111 look free
there and are `loops.shape`, `loops.speed` and `strobe0.decay`. Read the source
instead; `probe/ccs.py` in the scratchpad does it with `ast`.

## Metas

The third argument to `cc()` says what the knob means, and the UI reads it to
draw the control. `FloatRange(start, end, unit, geometric)` for a continuous
one, `CustomChoice({position: label})` for a list, `GradientChoice()` for a
gradient. Default is `FloatRange(0, 127)`.

**A `CustomChoice` indexes the CC value directly** — `{0: "a", 1: "b", 2: "c"}`,
not spread across 0–127. Spreading cannot survive a new option: adding a fourth
would move all three of the others, and every recording of that knob would come
back meaning something else. See `py/migrations/2026-11-04-choice-knobs/` for
the time that was fixed and what it cost.

The consequence is that a discrete control on a physical absolute knob only
uses the bottom of its travel. `rotary.parts` on KA6 is like this. Fixing it
properly means scaling incoming CC per meta rather than spreading the lists.

**A `GradientChoice` holds an index, and an index only means something if the
list never reorders.** A knob at 0–63 is on a gradient declared in
`instrument/gradients.py`, by its place in `GLOBAL_GRADIENTS`; a knob at 64–127 is
on one of the playing preset's own, by its place in the preset's `gradients` list
(64 is its first). A knob is on the gradient at *exactly* its index and on none
where there isn't one (it reads 0, which is dark); it is never snapped to the
nearest. `GLOBAL_GRADIENTS` is append-only: never remove or move one, because a
preset's knob holds the number. A preset's own list is ordered too, so deleting
one moves the ones after it. The server refuses a preset with more than 64 of its
own, or one with no stops. The names are for the UI to show.
The three knobs are `gradient_1.select` to `gradient_3.select`, each shared by
its `_h` and `_s` operators; see `fields/gradients.py`.

## Adding a control: the checklist

1. Pick a free number from the list above, confirmed against the source.
2. `midi.for_("<name>")` where `<name>` is **exactly** the attribute name in
   `FIELDS` / `OPERATORS` / `EFFECTS` — unless you are deliberately sharing one
   owner between two objects.
3. Give it a meta. Index the CC directly for anything discrete.
4. If it is an operator, check it is not another name plus a suffix.
5. Restart the instrument. `/rig` and `/controls` are built at startup from the
   class bodies, so a running rig will not show it.
