# Indexing & coordinate systems

Design notes for how edges, ends, modules, and hexes relate. This is the
addressing model the code should converge on.

## Architectural boundary

- **Everything outside the app uses the `ModuleEdgeCoord` system.** The viewer,
  the data structure it lights, and the hardware addressing are all in
  module/edge terms.
- **The app (`app.ts`) is where the translation to the hex grid happens.** The
  hex grid is an app-side convenience for authoring; it does not leak outward.

## The fundamental objects: edges and ends

- The core unit is the **edge** (a tube). Every edge has a **topmost end** and a
  **bottommost end** — this is intrinsic and always present.
- The core `Edge` object stores its two ends **always ordered top → bottom**,
  regardless of the context it is viewed in.
- Given an edge in a module, you can get a **vector for a filament** (the edge's
  direction / geometry).
- **Ends are the fundamental thing we are ultimately trying to reach.** Colours
  are set on ends; everything else is addressing to locate ends.

## Coordinate systems (indices)

Several indices exist over the same underlying edges/ends:

1. **Modules & edges** — the most basic system. A module has edges; each edge
   has a topmost and bottommost end. (`ModuleEdgeCoord`.)
2. **Hexes with edges** — a hexagon has 6 edges. In this system an edge's two
   ends are referred to as **clockwise** and **anticlockwise**.
3. **Edge space** — edges mapped onto a 2D space with specific coordinates.

## End semantics per context

- **Module context:** an edge's ends are **topmost / bottommost**.
- **Hex context:** an edge's ends are **clockwise / anticlockwise**.
- **top/bottom is always meaningful**, even in a hex context — so edges always
  carry the top/bottom information. The clockwise/anticlockwise labels are a
  hex-relative *reinterpretation* of the same two physical ends, not a separate
  pair. The core `Edge` always keeps them ordered top → bottom.

## Relationships & required lookups

- Each **hex edge belongs to a module** (one module owns each edge).
- Given a **hexagon**, you can read off the filament ends **clockwise** or
  **anticlockwise** around it.

Navigation the model must support:

- **Hex → edges:** starting from a hex, get its (6) edges.
- **Edge → hexes:** starting from an edge, get its hexes.
- **End → edge:** given an end, get the single edge it belongs to.
- **Edge → hexes (with relationship):** given that edge, get its **1 to 2**
  hexes, **along with the relationship of each hex to that edge** (i.e. which
  hex-edge slot it occupies, and hence how top/bottom maps to
  clockwise/anticlockwise for that hex).

An edge is shared by **1 or 2 hexes** (interior edges belong to two adjacent
hexes, boundary edges to one). This sharing means end-centric addressing is the
common denominator: reach an end → its edge → the hex(es) that reference it.
