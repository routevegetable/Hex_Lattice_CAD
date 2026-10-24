# Visual cheatsheet for the scalar field: scope

Branch `visual-cheatsheet`, off `custom-presets`. Built; this is the scope it was built to.
Source: the Inbox entry in `TASKS.md`.

## Goal

From the formula editor, preview what any part of a formula does: a small 3D rig
shows each end's value 0..1 as a colour. It is a cheat sheet for how a scalar field
shows up on the rig.

## Decisions (agreed)

| question | answer |
|---|---|
| where values come from | **the server**: the real field code runs, so the preview cannot drift from the rig |
| rig drawing | **small 3D**, a cut-down version of `Viewer/index.html` (three.js) |
| pad meaning | **the same trigger the real pad sends**: press = note-on, release = note-off |
| entry points | **every node of the tree, and the whole slot** |

## Behaviour

- **Colour**: value 0 is red, 1 is blue, through purple (hue range fixed, the same for
  every slot; a hue slot's own 0..2 wheel is ignored here). Out-of-range values clamp.
- **Rig modes**: two, with a toggle: **Hex 60°** and **Flat**. These are the two
  lateral-hinge-angle presets in `index.html` (`hex` = five 60° joints, `flat` = ten 0°).
  Each is a simpler rig than the full Lattice Viewer: no module/hinge detail, just
  the ends coloured.
- **Placement**: a popup opened by a preview button at each level of the formula
  editor (the slot root and every operand beneath it). It renders only that
  sub-tree, on its own, whichever slot it came from.
- **Pads**: if the sub-tree uses a pad, the preview presses it for 1 s, releases it
  for 1 s, and loops. Several pads in one sub-tree press and release together.
  Fields that animate on a press (ripple, wipe, burst) play as on hardware.

## Pieces

1. **Server**: an endpoint (say `POST /preview`) taking a formula tree plus a time
   and pad state, and returning one value per end. Runs on a scratch copy of the
   fields so it never touches the playing preset's state. Needs a decision on how
   it steps time (see open points).
2. **Mini viewer**: a three.js component for the two layouts, colouring ends by
   value. Reuses the geometry code from `index.html` where possible; that file is
   a 1100-line single page, so extracting what we need is part of the work.
3. **Popup in v3**: a button per formula node in `v3.js`, and a popup holding the
   viewer, the mode toggle, and the pad loop clock.
4. **Glossary**: one entry in `docs/glossary.md`.

## Open points for the build

- **Time** (decided): the server streams frames over a websocket (like `/ws/knobs`)
  while the popup is open.
- **Isolation**: fields hold state (notes held, ripples in flight). The preview needs
  its own copies, not the live ones.
- **Faders and knobs** (decided): no press to simulate, so they are held at **0.5**,
  not at their live value.
- **Ends** (decided): one value per end, one colour per end.
- **No tests today** cover the v3 front end, so verification is by looking at it in
  the browser.

## Out of scope

Editing from the popup; saving previews; showing the live rig's values;
anything for the mobile page.
