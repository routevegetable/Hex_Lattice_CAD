# Glossary

Words this project uses in a particular way. Where a term is ordinary English
somewhere else, this is what it means here.

## The structure

**Lattice** — the physical thing: a honeycomb of LED-lit edges. Everything
else is a way of addressing part of it.

**Module** — one physical board. A module spans **two tiles** across and one
down, which is why `LatticeWriter` is built with `COLS / 2`.

**Tile** — the unit the geometry is written in: one hexagon's worth of edges
and vertices, addressed `graph.TILE[x, y]`. The grid **wraps** in both
directions, so tile `(-1, 0)` is the one at the far right. Code that measures
distance or direction has to fold the result the short way round — see
`wrapped_step` in `fields/trace.py`.

**Edge class** — `A`–`F`, the six edges belonging to a tile. `C` and `F` are
the vertical ones.

**Edge** — an edge class plus a tile. An `EdgeRef`.

**End** — one end of an edge, `top` or `bottom`. An `EndRef`. This is the
smallest thing a field has a value for, and the thing the renderer writes to.
Note that an end is also *a direction*: travelling "out through an end" means
going from it to the other end of its edge.

**Vertex class** — `ABC`, `ABF`, `CDE`, `DEF`, each named for the edges that
meet there. Within a tile they stack bottom to top in that order: DEF, CDE,
ABC, ABF.

**Vertex** — a vertex class plus a tile. Three ends meet at one.
`ends_cw()` returns them clockwise, and **index 0 is always the vertical**.
At a CDE or an ABF that vertical points *up*; at a DEF or an ABC it points
*down*. That asymmetry is why `FireField` branches at DEF and ABC and goes
straight on everywhere else.

**Row** — a horizontal line of vertices. Four rows to a tile, so a lattice
`graph.height` tiles tall has `graph.height * 4` of them. Every step of an
upward path crosses exactly one.

**Filament** — one of the four LED runs at an end. `lattice[end][0..3]`.
Eight pixels to an edge.

## The effect chain

**Field** — AKA a 'scalar field'. A thing which produces some scalar value for every 'end' in the lattice.
A field is essentially a function: `get(now, end) -> float`.
Fields are expressions, built from combining other fields with operators like `+ - * /`.
Fields are attached to parts of the control surface - knobs/CCs and notes.
A field may share a control with another field.
Fields plug into **slots**.

**Effect** — Code which draws on the lattice. An effect has a number of **slots**, which receive values from fields.
An effect is essentially a function: `render(now, lattice, graph)`.
Effects are applied 'in order'. Note that it doesn't output things to draw - instead,
it mutates the latticewriter - this allows an effect to operate on the outputs of previous effects,
for the sake of blending and other transformations.

**Slot** — A thing on an effect that a field plugs into. It has a name.

**Muted** — an effect that is silenced without leaving the patch. It is skipped
when drawing, so the rig looks as if it were not there, while its slots keep
their fields. Muting is for looking at one thing at a time, so it is not part
of a preset: it is never saved, and selecting a preset clears it. `PUT /muted`
takes exactly the effects to silence and unsilences the rest.

**Patch** — An assignment of fields to slots, and a set of control surface CC values.
This is everything that makes a given effect chain's behavior.
The whole patch is replaced on post by the UI, which sends every slot it
knows about even when only one of them changed. A patch is the whole picture
to whoever applies it: a slot it does not mention ends up empty.

**Preset** — a numbered patch, 0–15, one `presets/NN.json` each. Every slot in
the bank always holds a patch; one with no file holds a patch that says
nothing, which applies cleanly and blanks the rig.

**Bank** — `PresetBank`. Holds two copies of every preset: the **cache**, which
is live and may have been edited, and the **stored** copy, which is what is on
disk.

**Dirty** — a preset whose cache differs from its file. Shown as an amber
number in the preset list and an amber dot on the preset chip. Saving writes
the cache out; reverting throws it away and reads the file back.

**Rig** — the *vocabulary*, as opposed to the settings: which fields exist,
which slots exist (including empty ones), what the bank holds. Served by
`/rig`. A patch names things; the rig says what there is to name.

**Console** — the one thread-safe way in. The render loop holds its lock for a
whole frame, so the API thread can never land a patch halfway through one.

## MIDI

**Control** — a knob or a pad the instrument watches. `cc 77`, `note 42`.

**Comment** — what a control is *for*, as `field.role` — `rotary.period`,
`fire.rate`. A control can have several, because more than one field can watch
the same knob. Shown in the knob readout and on the Configuration → MIDI page.

**`MIDIFor`** — a MIDI object that names what it is asking on behalf of.
`midi.for_("rotary").cc(KA5, "period")` leaves the comment `rotary.period`.
Fields are handed one of these rather than the MIDI object itself.

**Watched** — a control something actually asked for. A stray that merely
turned up on the wire (a bank select, an all-notes-off) still gets recorded so
it can be seen arriving, but it is not a setting and never enters a preset.
That filter is what keeps **dirty** meaningful: the fold only merges, never
prunes, so folding strays would re-dirty a just-committed preset.

**Hidden** — plumbing rather than a knob. The 16 step buttons are hidden: they
are watched and saved, but picking a preset is not someone turning a knob, so
they stay out of the readout.

**Pressure** — a note's aftertouch. Set from the velocity when the key goes
down, moved by polytouch after that, and *not* cleared on release — the last
press stands as a level.

**Step buttons** — CCs 20–35, one preset each. A press arrives as 127. A
program change of 0–15 does the same thing.

## The web UI

**Tab bar** — the top row: Controls, Effects, Configuration. Picks which page
is showing. The frame rate, preset chip, save and revert sit to its right.

**Sub bar** — the row under the tabs. What it indexes depends on the tab:
effects, fields, or the parts of the setup.

**Page** — the area below the sub bar, filled by whichever tab is up.

**Slot row** — on the Effects page, one slot of the chosen effect. Tapping it
opens the tree editor underneath.

**Tree editor** — how an expression is built by thumb: each operand is either
a field (𝑓(x)), a constant (a slider) or a `math` node with two operands of
its own. It writes back only when every operand is filled.

**Picker** — the modal over the page, used to choose a field and to list
presets.

**Knob readout** — the bar that appears along the bottom for two seconds
whenever a watched knob moves, showing what it is for, its value and a dial.
Preset loads do not raise it: a knob a preset put back is not one anybody
turned.

**Preset chip** — the top-right button showing which preset is playing, amber
with a dot when it has unsaved edits. Tapping it opens the preset list.

## Running

**Frame** — one pass of the render loop: clear the lattice, read MIDI, let
every effect draw, send it.

**Tick** — `MIDI.tick()`, draining the MIDI port once per frame. Controls that
moved during a tick are latched once at the end, so a burst keeps its last
value.

**Art-Net universe** — 512 channels of DMX arriving over UDP 6454, read as an
image. Each tile is a 2×2 square of pixels, one per vertex. Four universes,
each giving `r`, `g`, `b` and their average as fields.
