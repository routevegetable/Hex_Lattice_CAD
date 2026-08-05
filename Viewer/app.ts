// Hot-reloaded render module for the Hinge Hexagon filament installation.
//
// The viewer re-pulls this file on a short interval, transpiles it, and swaps in
// the exported `render` live — no page reload. `render(t)` returns the whole
// installation as frame[height][lateral] = ModuleFrame (see frame.ts).
//
// A module has 12 edges (A1..F2). Each edge has a top and bottom end; each end
// carries 4 filament colours. The viewer draws each strand as a gradient from
// its top-end colour to its bottom-end colour. Colour is linear RGB 0..1 (values
// may exceed 1 to drive the bloom). Anything out of range stays dark.

import { ModuleEdge, ModuleFrame } from "./frame";
import { EndRef, HexGridCoord, TileRef, VertexClass, VertexRef } from "./graph";

export type RGB = [number, number, number];
export type EndFrame = [RGB, RGB, RGB, RGB];             // 4 filaments at one end
export type EdgeFrame = { ends: { top: EndFrame; bottom: EndFrame } };
export type ModuleFrame = EdgeFrame[];                   // 12 edges (A1..F2)
export type Frame = ModuleFrame[][];                     // frame[height][lateral]

// Installation size to fill (rows stacked high, modules around each ring).
const ROWS = 2;
const PER_ROW = 32;
const EDGES = 12;
const FILAMENTS = 4;

// --- helpers ---------------------------------------------------------------
function hsv(h: number, s: number, v: number): RGB {
  h = ((h % 1) + 1) % 1;
  const i = Math.floor(h * 6), f = h * 6 - i;
  const p = v * (1 - s), q = v * (1 - f * s), u = v * (1 - (1 - f) * s);
  switch (i % 6) {
    case 0: return [v, u, p]; case 1: return [q, v, p]; case 2: return [p, v, u];
    case 3: return [p, q, v]; case 4: return [u, p, v]; default: return [v, p, q];
  }
}

function end_frame(f: Frame, er: EndRef): EndFrame {
  const mf = f[er.tile.y][Math.floor(er.tile.x / 2)];
  return ModuleFrame.get_end_frame(mf, er);
}

// Build one ModuleFrame from a colour callback. `end` is 0 (top) or 1 (bottom).
function module(color: (edge: ModuleEdge, filament: number, end: number) => RGB): ModuleFrame {
  const edges: ModuleFrame = [];
  for (let e = 0; e < EDGES; e++) {
    const face = (end: number): EndFrame =>
      Array.from({ length: FILAMENTS }, (_, f) => color(e, f, end)) as EndFrame;
    edges.push({ ends: { top: face(0), bottom: face(1) } });
  }
  return edges;
}

// --- the render function ---------------------------------------------------
// Called every frame with the time in seconds. Edit freely and save — it live
// reloads. Default: a per-edge hue with a wave travelling down each strand.
export function render(t: number): Frame {
  const frame: Frame = [];


  for (let height = 0; height < ROWS; height++) {
    const row: ModuleFrame[] = [];
    for (let lateral = 0; lateral < PER_ROW; lateral++) {
      row.push(module((edge, filament, end) => [1,1,1]));
    }
    frame.push(row);
  }

  for(let end of HexGridCoord.ends({x: 0, y: 0})) {
    const ef = end_frame(frame, end);

    for(let led of ef) {
      led[0] = 1
      led[1] = 0
      led[2] = 1
    }
  }


  TileRef.from(0,0).vertex(VertexClass.CDE)
  return frame;
}
