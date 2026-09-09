# Lite 2D Viewer — Implementation Plan

Goal: a new, genuinely lightweight viewer for the hex lattice that runs well on
a 2017 MacBook Pro. Lives alongside the existing `index.html` (full 3D) and
`lite.html` (3D minus bloom/reflections — still too heavy). This plan is for a
fresh Claude Code / VS Code session to pick up and execute.

## Workflow: three-step process per phase

Every phase below (Phase 0 through Phase 7) is executed in three steps, in
order. Do not skip a step or merge it into another.

1. **PM step — requirements check.** Before writing any code, re-read that
   phase's requirements (its numbered list, plus anything it draws from the
   "Requirements" and "Key existing references" sections above). Confirm they
   are:
   - **Complete** — nothing needed to finish the phase is missing or implied
     but unstated.
   - **Actionable** — each item is concrete enough to implement without
     further guessing (specific files, functions, formats, values — not
     vague direction).
   - **Verifiable** — the phase has an obvious, checkable "Done when" (see
     each phase's own criteria below). If a phase doesn't have one yet, write
     one before proceeding.
   If anything fails these checks, **update this plan document first**
   (edit the phase's steps and/or its "Done when" criteria), then continue.
   Only after the requirements are solid does the eng step begin.
2. **Eng step — implementation.** Implement the phase per its (possibly
   just-updated) numbered steps.
3. **QA step — verification.** Check the phase's "Done when" criteria one by
   one. Fix any gaps before moving to the next phase's PM step. Note
   anything discovered during QA that changes assumptions for later phases
   (add it to "Open items to confirm with the user" if it needs the user's
   input).

**Marking a phase complete:** once its QA step passes, mark the phase's
heading below with `— ✅ Completed <timestamp>`, using a full date+time (not
just the date), e.g. `## Phase 0 — Setup — ✅ Completed 2026-09-08 08:49:52 PDT`.
This is so a later session (or the user) can see not just which phases are
done, but when — useful for judging how stale a "done" phase's assumptions
might be.

## Requirements (confirmed with the user)

- **No WebGL/three.js at runtime.** Plain 2D Canvas (or SVG — Canvas is the
  default assumption below; switch if profiling says otherwise).
- **Layout**: simplified regular hex grid — not true per-joint hinge-angle
  physics. User picks modules-across and modules-up.
- **Nodes** (hinge/joint points): rendered with a shape derived from the real
  hinge geometry (not a generic circle/placeholder), extracted **once,
  offline**, from the existing 3D asset — baked into the 2D app as a static
  vector shape. Same fixed orientation at every joint (no per-joint rotation
  since the grid is simplified/regular). Must look faithful to how the hinge
  tube reads in `index.html` (translucent grey tube).
- **Fibers** (the 4 filament RGBs per edge end — the most important visual):
  each edge is drawn as 4 curved strands sharing the edge's two endpoints — 2
  nearly straight down the middle, 2 bowed outward and back — so all 4 pinch
  together at each node, like a lens/braided-cable shape. Should read as a 2D
  flattening of the real filament geometry in `index.html`
  (`FIL_OFFSETS`/`buildFilaments`), not an unrelated new look.
- **Data**: hybrid. Connect to `serve.py`'s existing WebSocket immediately
  (same `ModuleFrame` binary protocol as `index.html`/`lite.html` — no server
  changes needed). While no WS frame has arrived yet (or if disconnected),
  auto-cycle a built-in test pattern so there's always something on screen.
- **File**: new file alongside `lite.html`, e.g. `lite2d.html`. Do not modify
  `index.html` or `lite.html`. `serve.py` should not need changes — verify
  this assumption in Phase 5.

## Key existing references (read these before writing code)

- [`py/pylattice/frame.py`](py/pylattice/frame.py) and
  [`ts/lib/frame.ts`](ts/lib/frame.ts) — the wire format: a module has 12
  edges (`A1..F2`), each edge has a top/bottom end, each end has 4 filament
  RGBs (floats 0..1, may exceed 1 for bloom — clamp for 2D).
- [`serve.py`](serve.py) — WebSocket bridge. Binary frames pushed to `/ws`,
  push-only (never reads from the browser). Datagram format documented at the
  top of the file. Also exposes `GET/POST /lattice-shape` (`levels`,
  `perRow`) so Python examples can size themselves to what's built in the
  browser — the new viewer should POST its shape here too, same as
  `index.html`/`lite.html` do.
- [`index.html`](index.html) lines ~155-354 — the real filament rendering
  (`FILAMENT_HALF`, `FIL_OFFSETS`, `buildFilaments`, `updateFilaments`) and
  the tube-classification logic (`prepFilaments`, `extractTubeFromMeshes`) —
  this is the geometry the 2D fiber braid should visually echo.
- [`MEASUREMENTS.md`](MEASUREMENTS.md) — units, hinge pin positions, stacking
  increment, axis convention (X lateral, Y depth, Z vertical — face-on view
  for the node silhouette should project along Y).
- [`indexing.md`](indexing.md) — the module/edge/hex/end addressing model.
  The 2D grid only needs the hex-grid layer for laying modules out; keep the
  `ModuleEdgeCoord` semantics intact for anything that talks to
  `moduleStates`/WS data, per the architectural boundary it describes.
- [`hinge_obj/scheme.md`](hinge_obj/scheme.md) — confirms filament-to-edge
  and filament-to-spatial-position mapping is arbitrary; only end-to-end
  consistency matters. So the "2 straight / 2 bowed" assignment among the 4
  filament indices is a free visual choice, pick something and keep it fixed.

## Phase 0 — Setup — ✅ Completed 2026-09-08 08:49:52 PDT

### PM step
Confirm before starting: "empty shell" means head/panel scaffolding only (no
functional grid/rendering yet), and "serves unmodified" means no edits to
`serve.py`. If either is unclear when picked up, clarify/update this section
before implementing.

### Eng step
1. Create `lite2d.html` as an empty shell (structure copied from `lite.html`'s
   `<head>`/panel scaffolding minus the three.js importmap — no `<script
   type="importmap">` needed since there's no three.js).
2. Confirm `python3 serve.py` still runs and serves static files from this
   directory unmodified — `lite2d.html` just needs to be a sibling file.

### QA step — Done when
- `lite2d.html` exists, loads in a browser with no console errors, and shows
  the empty shell/panel scaffolding.
- `python3 serve.py` starts without error and `lite2d.html` is reachable
  over HTTP from it, with `serve.py`'s source unchanged.

**Implementation notes (2026-09-08):** since Phases 1-3 were done in the same
pass, the panel scaffolding built here already includes the modules-across/
modules-up inputs and Rebuild button — those turned out to be needed
immediately to drive/test Phase 2's grid model, and happen to be exactly
Phase 6's full panel spec anyway (minus the connection-status indicator,
which needs Phase 5's WS work first). `serve.py` confirmed unmodified —
`curl localhost:PORT/lite2d.html` returns 200 with no server-side changes.

## Phase 1 — Offline node-shape extraction (one-time script, not part of the app) — ✅ Completed 2026-09-08 08:49:52 PDT

Goal: produce a small, static 2D outline of the hinge tube ("Small-Small
Tube" per `MEASUREMENTS.md`) that gets pasted into `lite2d.html` as a
constant (SVG path string or array of points) — no OBJ/glTF parsing happens
at runtime in the browser.

### PM step
Confirm the tube-isolation approach (matching by object/group name or
material in the `.obj`/`.mtl`, mirroring how `prepFilaments()` finds it via
`/tube/i.test(name)` in the GLTF path) is still accurate against the current
`hinge_obj/Hinge Hexagon.obj`/`.mtl` before writing the extraction script —
if the grouping/material names have changed, update step 1 below first.

### Eng step
1. Write a standalone script (e.g. `hinge_obj/extract_node_shape.py`,
   stdlib-only per the `pylattice` convention, or use `trimesh`/`numpy` if
   already available) that:
   - Loads `hinge_obj/Hinge Hexagon.obj`.
   - Isolates the hinge tube geometry (the grey "Small-Small Tube" group —
     same group `prepFilaments()` in `index.html` finds via `/tube/i.test(name)`
     on GLTF node names; for the raw `.obj` you'll need to match by the `o`/`g`
     object name or by material, see `.mtl` grey material).
   - Projects those vertices to 2D by dropping Y (depth) — i.e. a face-on
     (X, Z) view, per the axis convention in `MEASUREMENTS.md`.
   - Computes a simplified outline (concave hull / alpha-shape, or just the
     mesh's boundary edge loop) — aim for a few dozen points, not the full
     vertex cloud.
   - Normalizes it to a small local coordinate space (e.g. centered on
     origin, unit-scaled) so it's easy to place/scale per node in the 2D app.
   - Prints/writes the result as an SVG path `d` string or a flat JS array
     literal, ready to paste into `lite2d.html`.
2. Visually sanity-check the extracted outline (e.g. render it standalone in
   an SVG or matplotlib) against `index.html`'s rendered tube before using it.
3. Paste the result into `lite2d.html` as a constant (e.g. `const
   NODE_SHAPE_PATH = "M ... Z"`).

### QA step — Done when
- The extraction script runs standalone and produces an outline.
- A side-by-side check (extracted outline vs. `index.html`'s rendered tube)
  confirms the silhouette is recognizably the same shape, not just "a blob."
- `NODE_SHAPE_PATH` (or equivalent) is present in `lite2d.html` as a static
  constant — no OBJ/glTF loading code exists in the shipped app.

**Implementation notes (2026-09-08):** the `.obj` (unlike the GLTF path
`prepFilaments()` uses) has 6 contiguous `g Small-Small Tube` blocks;
classified vertical vs. diagonal by bbox aspect (Z range > 2× X range, same
test as `prepFilaments()`) — found exactly 2 verticals, matching the C/F
split. Picked the smaller-mean-X one (C, the hinge pin) as the node shape,
per the "leftmost tube = left hinge" comment in `lite.html`. Its vertex
cloud confirms it's a plain flat-capped, axis-aligned cylinder (circular
cross-section, uniform end-cap Z) — so its face-on (X,Z) convex hull is a
4-point rectangle, not a rounded/organic shape. That's the correct, faithful
silhouette of the real geometry, not an extraction bug — a straight pin read
from the side just is a bar. Sanity-check render: `extract_node_shape.py`
plus a throwaway matplotlib script (not committed) confirmed the shape.
Script and output: [`hinge_obj/extract_node_shape.py`](hinge_obj/extract_node_shape.py),
constant pasted into `lite2d.html` as `NODE_SHAPE_PATH`/`NODE_SHAPE_POINTS`.

## Phase 2 — Grid model (JS, in `lite2d.html`) — ✅ Completed 2026-09-08 08:49:52 PDT — 🔧 Revised 2026-09-08 09:03:46 PDT

### PM step
Confirm "simplified regular hex grid" (fixed spacing/geometry, no
hinge-angle math) and the exact `moduleStates`-shaped in-memory structure are
still the intended scope — this phase should not grow into real physics.
Update this section if the fallback test pattern (Phase 5) or renderer
(Phases 3-4) end up needing grid data this phase doesn't yet produce.

### Eng step
1. Define the simplified regular hex grid: given `perRow` (modules across)
   and `levels` (modules up), compute node (joint) positions and which nodes
   each module's edges connect. Keep this decoupled from real hinge-angle
   math — fixed hex spacing/geometry is fine.
2. Reuse the `ModuleFrame` shape from `frame.ts`/`frame.py` conceptually: an
   in-memory array of modules, each with 12 edges, each edge with
   top/bottom ends of 4 RGB floats — this is what WS frames (and the
   fallback test pattern) write into, and what the renderer reads from.
3. POST the shape to `/lattice-shape` on build, same as the other two
   viewers, so `pylattice` examples can size to it.

### QA step — Done when
- Given sample `perRow`/`levels` values, the grid produces the expected node
  count and edge/module connectivity (spot-check by logging or a quick
  visual scatter-plot of node positions).
- The in-memory module/edge/end structure matches the `ModuleFrame` shape
  closely enough that Phase 5's WS parsing can write directly into it.
- Building the grid POSTs to `/lattice-shape` and `GET /lattice-shape`
  reflects the new `levels`/`perRow` values.
- Every module above the ground level (`h > 0`) has vertical leg edges
  connecting it down to the corresponding module one level below — modules
  are not visually floating/disconnected from the rest of the lattice.

**Implementation notes (2026-09-08):** re-reading `scheme.md`/`frame.ts`
clarified that a **segment is one full regular hexagon** (6 sides A/B/C/D/E/F
— C and F are its vertical left/right hinge sides, A/B/D/E the four
diagonals), not a half-hexagon as first assumed — "module = 2 segments side
by side" means 2 adjacent hexagons in a ring, sharing their vertical C/F
edge (`frame.ts`'s `tile.x % 2` alternation is exactly this segment parity:
suffix "1" = segment 0, "2" = segment 1). So the flattened grid is
implemented as **rows of chained regular hexagons**: each level (`h`, 0..
`levels-1`) is a horizontal strip of `2*perRow` regular hexagons (flat
vertical left/right sides, pointed top/bottom), consecutive hexagons sharing
a vertical edge; rows are stacked with a visual gap (levels don't share
edges in the real model either — see `MEASUREMENTS.md`'s independent stack
transform). `moduleGrid[h][l]` (`l` = module/pair index, 0..`perRow-1`)
matches `index.html`/`lite.html`'s WS routing addressing exactly, so
Phase 5 can plug in unmodified. Each module's 12 edges are drawn as two
full hexagons' worth of 6 sides each; the vertical edge shared between a
module's own two segments (and between adjacent modules) is drawn twice
(once per segment's independent tube instance) — geometrically coincident,
which mirrors the real 3D model (two physically-adjacent tube meshes at the
same hinge location) rather than being a bug. Revisit only if Phase 4
fiber-braid overlap there looks wrong. Implemented in `lite2d.html`'s
`buildGrid()`/`hexVertices()`/`HEX_SIDES`.

**Revision (2026-09-08 09:03:46 PDT):** the user pointed out modules above
the ground level weren't connected to anything — this grid drew rows as
independent gapped strips with no vertical linkage at all, so a 3-level
build looked like 3 disconnected sheets stacked with dead space between
them. Fix, informed by the Phase 4 PM-step research into the real geometry
(the OBJ's "F" tube sits near a segment's own local center, not at a lateral
extreme — i.e. it's a leg/spine, not a second lateral hinge): **F is no
longer a lateral hexagon side.** `HEX_SIDES` now only carries the 5 true
lateral sides (A, B, C, D, E) — a hexagon's "right" side is never drawn
twice, it's just the next hexagon's own C sharing the same 2 nodes (the real
segment only has one explicit hinge tube too). F1/F2 are now vertical: each
hexagon's top point connects straight down, across the row gap, to the
corresponding hexagon's bottom point one level below — the "legs" the user
asked for. Also flipped row placement so `h=0` (ground) renders at the
**bottom** of the canvas and increasing `h` stacks upward (previously `h=0`
was drawn at the top, which read backwards next to "modules up"). Ground-
level hexagons (`h=0`) still have no leg, since there's nothing below them —
the same real-world case `index.html`'s "hidden top tube" handles, which
this grid otherwise has no analog for. Verified with a headless-Chrome
screenshot (temporary random-color seeding, removed after) — legs render
with the same 4-strand fiber treatment as lateral edges, no Phase 4 code
changes were needed (`drawFiberEdge` only cares about two node endpoints
and an edge's color data, not what kind of connector it is). Edge count for a 6×3 grid: 204 (was 216 pre-revision — the 36 old F lateral
edges, 12 per row × 3 rows, are gone; 24 new vertical legs replace them, 2
segments × 6 modules × 2 non-ground rows — a net −12).

## Phase 3 — Node rendering — ✅ Completed 2026-09-08 08:49:52 PDT

### PM step
Confirm Phase 1's `NODE_SHAPE_PATH` and Phase 2's node positions are both
ready as inputs. If Phase 1 QA flagged the shape as illegible at small
sizes, resolve that before starting this phase rather than compensating here.

### Eng step
1. Draw `NODE_SHAPE_PATH` (from Phase 1) at every joint position, same fixed
   orientation everywhere, sized to fit the grid scale.
2. Confirm it reads clearly at the zoom level the grid will typically be
   viewed at — adjust the extraction/normalization from Phase 1 if it's
   illegible at small sizes (simplify the outline further rather than
   shrinking detail that won't render).

### QA step — Done when
- Every joint in the built grid shows the node shape, consistently
  oriented and sized.
- At the default/typical zoom level, the node shape is legible (not a
  smudge or an oversized blob) — checked visually, not just "it renders."

**Implementation notes (2026-09-08):** Phase 1's outline is a true-aspect
~1:14.8 (width:height) bar — rendered at that aspect it would be sub-pixel
wide and invisible at typical grid zoom. Scaled **anisotropically** instead
(fixed pixel half-width/half-height, not a uniform scale factor) to keep it
a legible small pin marker; this is the "adjust ... for legibility" call the
PM step flagged, applied at the render step rather than by further
simplifying Phase 1's already-minimal 4-point outline. Verified visually via
a headless-Chrome screenshot of `lite2d.html` (6×3 grid: 150 nodes, 216
edges, 18 modules — matches the expected count for chained-hexagon rows) —
individual node bars are crisp and distinct, correctly placed at the zigzag
hex-vertex tiers. Fit-to-view (`fitTransform()`) auto-scales/centers the
built grid in the canvas so this holds without manual pan/zoom.

## Phase 4 — Fiber rendering (the important part) — ✅ Completed 2026-09-08 08:57:44 PDT

### PM step
Confirm the straight/bowed assignment among the 4 filament indices has been
picked and will be documented in code (per `scheme.md`, the mapping is
arbitrary but must be fixed and consistent). Confirm whether the "hidden top
tube" question (see Open items) needs an answer before this phase can be
called done, or can be deferred to QA.

### Eng step
1. For each edge (between two adjacent node positions), draw 4 strands:
   - 2 "straight" strands: minimal curvature, close to the direct line
     between the two endpoints.
   - 2 "bowed" strands: curve outward (perpendicular to the edge) and back,
     using quadratic/cubic Bezier curves whose start and end points are
     exactly the edge's two node positions (so they naturally pinch together
     at both nodes — no separate alignment work needed).
   - Keep the straight/bowed assignment among the 4 filament indices fixed
     and consistent across all edges (per `scheme.md`, the mapping is
     arbitrary — just pick one and document it in a comment).
2. Color each strand from that edge's corresponding filament RGB (top-end
   color at one end, bottom-end color at the other — interpolate along the
   strand the same way `index.html`'s `VERT_T`-based coloring does, i.e.
   color gradient along the curve, not a flat single color).
3. Skip/hide the same "hidden top tube" edge case `index.html` handles
   (`isHiddenEdge`) if it's visually relevant in 2D — check whether it
   matters once the grid is on screen; may not apply the same way without
   the 3D "topmost tube" concept, confirm with the user if unsure.

### QA step — Done when
- Every edge shows 4 strands (2 straight, 2 bowed) that visibly pinch
  together at both endpoint nodes.
- Strand colors visibly interpolate between the edge's top/bottom filament
  RGBs rather than rendering as a flat single color.
- The straight/bowed filament-index assignment is documented in a code
  comment and applied identically across all edges.
- A decision on the "hidden top tube" case is made and recorded (either
  implemented, or explicitly deferred with the user's input logged in "Open
  items").

**Implementation notes (2026-09-08):** filament indices 0/1 fixed as
"straight" (small perpendicular offset), 2/3 as "bowed" (large offset);
grid-edge endpoint "a" fixed as the top end, "b" as bottom — both documented
in code comments in `lite2d.html` (`STRAND_OFFSETS`, `drawFiberEdge`). The
"hidden top tube" case was resolved as **does not apply**: this 2D layout's
rows are independent gapped strips (no vertical stacking connector), so
every edge already terminates at a real neighboring node — see the comment
above `STRAND_OFFSETS` in `lite2d.html`. Verified visually via a headless-
Chrome screenshot with edges temporarily seeded random RGBs (removed after
verification, not shipped) — 4 strands per edge pinch cleanly at both nodes
in a lens shape, colors visibly gradient along each strand, node markers sit
on top at the joints. `moduleStates` is still all-black by default (no real
color source until Phase 5), so the shipped file currently renders edges
that are present but invisible against the dark background — expected until
Phase 5 adds the fallback test pattern / live WS data.

## Phase 5 — Live data + fallback test pattern — ✅ Completed 2026-09-08 09:14:52 PDT

### PM step
Confirm the three states this phase must handle are unambiguous: (a) never
connected/no frame yet → test pattern, (b) connected with live frames → real
data, (c) disconnected after having been connected → test pattern resumes.
Confirm which example script(s) will be used for the live-producer check.

### Eng step
1. Open a WebSocket to `/ws` (same URL/protocol `index.html`/`lite.html`
   use) and parse incoming binary `ModuleFrame` datagrams into the module
   array from Phase 2 (reuse `ts/lib/frame.ts`'s parsing logic, ported to
   plain JS — no build step needed, this can be inlined or a small
   `<script>` module).
2. Track "has any real WS frame been received yet." While false (or if the
   socket disconnects), run a built-in auto-cycling test pattern
   (e.g. a slow moving rainbow/gradient across modules and filaments) so the
   view is never blank. Switch off the test pattern the moment a real frame
   arrives; switch back on if the connection drops.
3. Verify against a real producer: run `python3 -m pylattice.examples.wave`
   (or `four_colors.py`, `colors.py`) with `serve.py` running, confirm
   `lite2d.html` lights up correctly.

### QA step — Done when
- With `serve.py` running and no producer script active, `lite2d.html` shows
  the auto-cycling test pattern immediately on load (never a blank grid).
- Running `python3 -m pylattice.examples.wave` (or another example) while
  `lite2d.html` is open switches it to live data within one frame interval,
  and the fiber colors visibly match what `index.html`/`lite.html` show for
  the same producer.
- Stopping the producer / killing the WS connection switches the view back
  to the test pattern without a manual reload.

**Implementation notes (2026-09-08):** hit and fixed a real pre-existing bug
first — `py/pylattice/lattice_client.py` had an unresolved git merge
conflict (literal `<<<<<<<`/`=======`/`>>>>>>>` markers left in from commit
`2c3c0f0`), which raised `SyntaxError` on `import pylattice`, blocking any
live-producer test. Fixed by keeping both of the conflicting imports (`json`
and `math` — both are actually used in the file); unrelated to lite2d.html
otherwise. Chose `python3 -m pylattice.examples.wave` as the live-producer
check, per the plan's own suggestion.

Ported `ts/lib/frame.ts`'s `ModuleFrame.deserialize` to plain JS by hand
(`CHANNEL_EDGES`/`FLIP_ORDER`/`deserializeModuleFrame` in `lite2d.html`)
rather than transpiling `frame.ts` at runtime via the sucrase-CDN bundler
`lite.html` uses — same wire format, but no external-CDN dependency for a
"lite" viewer. This required changing `blankModule()`/`EDGE_NAMES` from a
string-keyed object to an index-addressed array (`EDGE_INDEX`, matching
`ModuleEdge` enum order A1=0..F2=11) so edges can be addressed numerically
the same way `frame.ts` does.

Caught a real gap during QA, not just a formality: **`serve.py`'s WebSocket
to the browser stays open even after the UDP producer process is killed** —
it's a plain relay, not tied to the producer's lifetime. So "stopping the
producer" does *not* fire a socket `close` event, meaning a close-event-only
implementation would leave the view frozen on the last live frame forever
instead of falling back. Fixed with an explicit staleness timeout
(`STALE_MS = 3000`, checked every animation frame against `lastFrameAt`) —
`liveData` drops back to false, and the test pattern resumes, whenever no
frame has arrived recently, regardless of whether the socket technically
closed. Status text distinguishes "disconnected" (socket actually closed),
"signal lost" (was live, no frames in >3s, socket still open), and
"connected, no frames yet" (never received one) — useful for debugging, and
a preview of Phase 6's connection-status indicator.

All three PM-step states were verified against the real `wave.py` producer
using a **persistent headless Chrome via the DevTools protocol** (plain
`--screenshot` one-shot mode was tried first but proved unreliable here:
`--virtual-time-budget` speeds up JS timers but not the real WebSocket
handshake, so screenshots were sometimes taken before a frame had actually
arrived) — screenshots at t=3s showed "live" while `wave.py` ran, and at
t=8s (5s after killing it, past `STALE_MS`) showed "test pattern (signal
lost)", confirming the full live → stale → fallback cycle end-to-end. Note:
`wave.py` hardcodes `ROWS=2, PER_ROW=32` rather than reading `/lattice-shape`
— with our grid's `liveData` flag being global (per the plan's own "has any
real WS frame been received yet" phrasing, not per-module), any module the
producer's shape doesn't cover (e.g. our third row, or any column beyond a
narrower producer) freezes on its last test-pattern frame rather than
continuing to animate or receiving data, once any frame arrives anywhere.
Matches the plan's spec as written; flagged here rather than treated as a
bug.

### Revision — per-module live/off state (requested by the user) — ✅ Completed 2026-09-08 09:53:02 PDT

**Requirement:** if live WS data is only targeting some of the visible
modules, the other (untargeted) modules should go **off** (black) rather
than showing — or being frozen mid-frame on — the test pattern. The test
pattern should still cover the whole grid in the original "nothing is live
anywhere" case; this only changes what happens to modules a live producer
isn't addressing once *something* is live.

#### PM step
Requirement check: is this complete/actionable/verifiable as stated above?
- **Complete** — yes: it fully specifies the two cases (some modules
  targeted vs. none) and the desired outcome for the untargeted case (off,
  not test pattern, not frozen-last-test-pattern-frame — the bug flagged in
  the note above).
- **Actionable** — yes, but it requires a state-model change: `liveData`
  today is a single global flag (whole-grid "are we receiving anything");
  this needs **per-module** live/stale tracking (does *this* module have a
  recent frame), plus a derived global "is anything live" for the
  connection-status indicator (Phase 6) to keep working unchanged.
- **Verifiable — Done when** (added as this revision's QA criteria):
  - With no producer running, the full grid shows the animated test pattern
    (unchanged from Phase 5).
  - With a producer targeting only part of the grid (e.g. `wave.py`'s
    `ROWS=2, PER_ROW=32` against a smaller built grid, or vice versa — any
    producer/grid combination where coverage is partial), modules it
    addresses show live data, and modules it does **not** address are black
    (all 4 strands, all filament indices) — not test-pattern colors, not
    frozen leftover colors from before "live" started.
  - A module that goes stale on its own (>`STALE_MS` since its last frame)
    while other modules are still live also goes black, not back to the
    test pattern (it's no longer being targeted either).
  - The moment *no* module anywhere is live/recent, the whole grid reverts
    to the animated test pattern again (the original global fallback).
  - The Phase 6 connection-status indicator (dot + label) still shows
    live/test-pattern/disconnected correctly — it reflects "is anything
    live," not per-module state.
Nothing here contradicts the phase's original scope, so no other plan text
needs updating before implementing.

#### Eng step
1. Replace the single global "has any frame arrived" check with per-module
   tracking: stamp a `_lastFrameAt` timestamp directly on each module object
   (in `grid.moduleStates`/`moduleGrid[h][l]`, which are plain arrays — a
   non-numeric property is fine) inside `routeLedMessage()`, instead of one
   shared `lastFrameAt`.
2. Each animation-frame tick, compute per-module `_live = (now - _lastFrameAt)
   < STALE_MS` for every module, and `anyLive = OR` of those. `anyLive`
   drives `liveData`/`updateStatus()` exactly as the old global flag did.
3. If `anyLive` is false: run the existing `updateTestPattern()` over every
   edge (unchanged — full-grid fallback).
4. If `anyLive` is true: for every edge whose owning module is *not*
   `_live`, zero its 4 filament RGBs at both ends (off) every tick; leave
   edges whose module *is* `_live` untouched (their colors are already
   correct from the last `routeLedMessage()` write).
5. Keep `everReceivedFrame` (global, never resets) for the status label's
   "signal lost" vs. "connected, no frames yet" distinction — unaffected by
   this change.

#### QA step
See the "Done when" list under the PM step above — verify each bullet with
a real partial-coverage producer against `serve.py`, using the same
headless-Chrome-via-DevTools-Protocol approach Phase 5/7 already validated
as reliable for this (plain `--screenshot` timing is not trustworthy for
live WS state).

**Implementation notes (2026-09-08):** implemented per the Eng step above —
`mod._lastFrameAt` stamped per module in `routeLedMessage()`, per-module
`_live` recomputed every `tick()`, `turnOffStaleModules()` zeros edges of
any non-`_live` module whenever `anyLive` is true, full-grid
`updateTestPattern()` only when `anyLive` is false. `liveData` is now a
derived value (recomputed each tick from per-module state) rather than a
value `routeLedMessage`/`ws.onclose` set directly.

QA hit two rabbit holes, both worth recording:
1. **A leftover test producer process from earlier in the session** (a
   `four_colors.py` run I'd started for the previous fix and never fully
   killed) kept broadcasting in the background and contaminated the first
   two verification attempts with confusing, seemingly-aliased results.
   Not a code bug — a reminder to verify `ps aux` for stray producers
   before trusting an unexpected result, not just trust the first
   explanation that fits.
2. **A real, separate pre-existing bug surfaced along the way:** `wave.py`
   calls `client.send(l, h, data)` (lateral, height) but
   `index.html`/`lite.html`/`lite2d.html` all parse the wire location as
   "height-lateral" — so `wave.py` (and `LatticeWriter.show()`, which has
   the same `(x=col, y=row)` call order) address modules transposed from
   what the viewers expect. This predates this session and affects the 3D
   viewers too; it's *separate* from the per-module feature itself, so
   verification used a throwaway correctly-addressed test producer instead
   of `wave.py` (not committed — scratch-only). Flagged to the user rather
   than silently fixed, since it touches files outside this session's
   scope and the "correct" convention needs a real decision, not a guess.
   **Also worth noting:** the `four_colors.py` fix made two sessions ago in
   this same conversation copied `wave.py`'s `(l, h)` call order verbatim —
   meaning that fix has the same transposition bug. Not corrected here
   (out of scope for this revision); flagged for the user alongside the
   `wave.py` finding.

Verified all four "Done when" bullets with headless-Chrome-via-CDP against
throwaway scratch producers (not committed): full test pattern with no
producer; a producer covering only 2 of 3 built rows leaves the third
row black while the covered rows show real data; killing one of two
concurrent per-row producers takes only that row black while the other
stays live and the status indicator correctly stays "Live data" (not
"signal lost") throughout; killing the last live producer reverts the
whole grid to the test pattern after `STALE_MS`. Screenshots confirmed
each state visually, not just via the `moduleLive`/`liveData` JS state
dump.

**A real bug surfaced during that verification, not just the two side
findings above:** `mod._live = now - (mod._lastFrameAt || 0) < STALE_MS` —
the `|| 0` fallback for "never received a frame" is wrong. `now` is
`performance.now()`, i.e. milliseconds since page load, so `now - 0` is
*small* for the first `STALE_MS` (3s) after every page load or rebuild —
meaning every module read as falsely "live" during that window, and the
grid showed nothing at all (neither test pattern nor real data, since
`turnOffStaleModules()` skips modules it thinks are live) instead of the
required "test pattern immediately, never blank." This directly undermined
this revision's own goal. It's a genuine race: some of the verification
runs above happened to check state *after* the 3-second window and passed
cleanly; a few didn't and showed it plainly (`liveData: true` with every
`moduleLastFrameAt` still `null`) — caught by re-checking a plain page load
with no producer at all, deliberately at several timestamps inside that
window (500ms/1500ms/2500ms), after an earlier "final sanity" screenshot
looked wrong and didn't match an isolated instrumented check moments
earlier — the discrepancy itself was the tell that something timing-
dependent was going on, not environmental noise. Fixed by checking
`mod._lastFrameAt !== undefined` explicitly instead of `|| 0`. Re-verified
the same three timestamps post-fix (all correctly `liveData: false`) and
re-ran the full partial-coverage and mixed-staleness scenarios above to
confirm the fix didn't disturb them.

## Phase 6 — Control panel / UI — ✅ Completed 2026-09-08 09:18:59 PDT

Minimal panel, much smaller than `lite.html`'s:
- Modules across / modules up (numeric inputs → rebuild grid).
- Connection status indicator (live / test-pattern / disconnected).
- Rebuild button.
Explicitly drop: room placement, camera walk controls, eye height, ambient
light HSV, transparent walls, hinge-angle textarea, presets — none apply to
a flat schematic 2D view.

### PM step
Confirm the panel scope above is still exactly right (no scope creep back
toward `lite.html`'s controls) before implementing.

### Eng step
Implement the panel as scoped above: two numeric inputs, a status indicator,
and a rebuild button, wired to Phase 2's grid builder and Phase 5's
connection-state tracking.

### QA step — Done when
- Changing modules-across/modules-up and clicking Rebuild regenerates the
  grid at the new size without a page reload.
- The status indicator correctly shows live / test-pattern / disconnected
  in each of those three real conditions (test by toggling the producer
  script and/or `serve.py`).
- None of the explicitly-dropped `lite.html` controls are present.

**Implementation notes (2026-09-08):** modules-across/up inputs and the
Rebuild button already existed (added in Phase 0, needed early to drive/test
Phase 2). Added a dedicated "Connection" section with a colored dot
(green/yellow/red for live/test-pattern/disconnected) + label, driven by the
same `liveData`/`wsOpen`/`everReceivedFrame` state Phase 5 already
maintains and already validated end-to-end — this phase only added the
panel-visible indicator, not new state logic. The floating canvas-corner
badge (`#status`) keeps Phase 5's finer-grained text ("signal lost" vs "no
frames yet") since the panel dot collapses those to one color; both read
from the same `updateStatus()` call so they can't drift out of sync.
Verified visually via headless-Chrome screenshot. Confirmed no dropped
`lite.html` controls (room placement, camera walk, eye height, ambient
HSV, transparent walls, hinge-angle textarea, presets) exist in the panel.

## Phase 7 — Performance validation — ✅ Completed 2026-09-08 09:28:56 PDT

### PM step
Confirm the target grid size(s) to test against (see "Open items" — this
must be pinned down, with the user if necessary, before QA can produce a
meaningful pass/fail).

### Eng step
1. Test on the actual 2017 MacBook Pro (or throttle CPU in dev tools as a
   proxy) with a realistically large grid (pick a size matching the real
   installation).
2. Confirm smooth interaction/updates at that size before considering it
   done. If the bowed-fiber Bezier redraws are a bottleneck at high module
   counts, consider caching per-edge paths and only re-coloring (not
   re-computing geometry) on each WS frame.

### QA step — Done when
- At the agreed target grid size, the view updates smoothly (no visible
  jank/dropped-frame stutter) on the real 2017 MacBook Pro or an equivalent
  throttled proxy, both on WS-driven updates and on the auto-cycling test
  pattern.
- If a caching optimization was needed to hit that bar, it's implemented and
  re-tested at the same size.

**Implementation notes (2026-09-08):** the target size wasn't pinned down by
the user, and this machine turned out to *be* the plan's actual target
hardware — `system_profiler` reports `MacBookPro14,2`, which is exactly a
2017 13" MacBook Pro — so testing happened on the real thing, no throttling
proxy needed. In the absence of a specified real-installation size, picked
20×10 (200 modules) as the "should be smooth" bar and 40×20/60×30 (800/1800
modules) as stress sizes, per the plan's "realistically large" phrasing;
flagged as a judgment call, not a user-confirmed number — revisit if the
real installation is a different order of magnitude.

Measured with a headless-Chrome + DevTools-Protocol harness (plain
`--screenshot` proved too unreliable for timing here, same lesson as Phase
5): `rebuild()` at each size, then 60 iterations of
`updateTestPattern(); draw()` timed directly (bypassing `requestAnimationFrame`
throttling, so this measures real achievable draw throughput, not
vsync-capped FPS).

| Grid | Modules | Edges | Before | After |
|---|---|---|---|---|
| 4×2 | 8 | 88 | 225 fps | 788 fps |
| 20×10 | 200 | 2,360 | **3.3 fps** | **29.6 fps** |
| 40×20 | 800 | 9,520 | 0.8 fps | 2.7 fps |
| 60×30 | 1,800 | 21,480 | (didn't finish in 120s) | 1.3 fps |

"Before" was the original Phase 4 renderer: each strand drawn as ~12
separate `beginPath`/`moveTo`/`lineTo`/`stroke()` calls (one per
color-gradient sample). That's exactly the bottleneck the plan's Eng step
anticipated, confirmed here rather than assumed. Two changes, both scoped to
`draw()`/`drawStrand()` in `lite2d.html`, no visual change intended or
observed (re-screenshotted to confirm):
1. Each strand is now **one** `Path2D` stroked **once**, colored with a
   `CanvasGradient` (2 stops, top/bottom RGB) along the strand's straight
   `pa`→`pb` axis instead of manually lerping color per sampled point. Since
   the bow is mild and monotonic along that axis, this is visually
   equivalent to the old per-vertex `VERT_T`-style coloring, at 1 draw call
   per strand instead of ~12.
2. Path2D geometry is now **cached** per edge/strand (`strandPaths()` /
   `_pathCache`) and only rebuilt when the grid is rebuilt or the view is
   resized (`scale`/`ox`/`oy` change) — not on every animation frame, since
   node screen positions don't change between those events even though
   colors do.

Net effect: ~9x faster at the 200-module bar (3.3 → 29.6 fps) — smooth
enough for a schematic status display, confirmed by re-screenshotting (no
visible jank in the static captures, and the fps number itself is the
jank-vs-smooth signal here). 800+ modules remain slow (≤2.7 fps) even after
both optimizations — at that scale the bottleneck shifts to raw
canvas-stroke rasterization cost (tens of thousands of gradient-stroked
curves per frame), which Canvas 2D fundamentally can't avoid without a
different rendering approach (WebGL, explicitly out of scope per the
Requirements' "no WebGL/three.js at runtime"). Documented as a known scaling
ceiling of the plain-Canvas2D approach rather than something to chase
further within this plan's constraints — revisit if the real installation
turns out to need 800+ modules on screen at once.

**Resolved (2026-09-08 09:33 PDT):** the user confirmed the real
installation will never exceed ~24 modules. Re-benchmarked at that actual
scale across a few across/up splits (6×4, 8×3, 12×2, 24×1 — all 24 modules):
272-341 fps in every case. This is an order of magnitude past the 200-module
"smooth" bar this phase originally targeted without a real number to aim
at — performance is a non-issue at the real target size, full stop. The
800+ module ceiling noted above is now known to be entirely academic for
this installation.

## Open items to confirm with the user during/after implementation

All phases (0-7) are implemented; these are follow-ups worth the user's
input rather than blockers:

- ~~Real-world grid size vs. measured performance ceiling.~~ **Resolved:**
  user confirmed the real installation never exceeds ~24 modules;
  re-benchmarked at that scale (272-341 fps across several across/up
  splits) — comfortably smooth, no further optimization needed. The
  800+-module slowdown noted below is now known to be academic for this
  installation.
- The "hidden top tube" edge case (Phase 4) was resolved as "does not
  apply" to this 2D layout, and the F-tube's real role (vertical stacking
  leg, not a second lateral hinge) was corrected into the grid model during
  the Phase 2 revision — both resolved during implementation, not deferred.
- **Final visual review** of the node shape (Phase 1, a plain rectangular
  bar — faithful to the real hinge pin's silhouette but not decorative) and
  the fiber braid (Phase 4) once seen on screen with real data (Phase 5) —
  these were designed from description/synthetic test colors, not a
  side-by-side with `index.html` under real producer output.
- `wave.py`'s hardcoded `ROWS=2, PER_ROW=32` (vs. reading `/lattice-shape`)
  means it doesn't exercise this grid's full extent or its vertical legs at
  the default 4×2 size — fine for Phase 5's pass/fail, but worth knowing if
  the user wants to see live data across the whole built grid.
