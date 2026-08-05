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
import { EdgeRef, EndRef, HexGridCoord, TileRef, VertexClass, VertexRef } from "./graph";

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

// 32-bit int -> int hash. Deterministic, well-distributed.
function hash(x: number): number {
  x = Math.imul(x ^ (x >>> 16), 0x7feb352d);
  x = Math.imul(x ^ (x >>> 15), 0x846ca68b);
  x ^=        x >>> 16;
  return (x >>> 0) / (0xFFFFFFFF >>> 0);               // unsigned 32-bit
}

function rand_period(now: number, salt: number, period_ms: number): number {
  return hash(Math.floor(now / period_ms) + salt)
}


// --- the render function ---------------------------------------------------
// Called every frame with the time in seconds. Edit freely and save — it live
// reloads. Default: a per-edge hue with a wave travelling down each strand.
export function render(t: number): Frame {

  const now = Math.floor(t * 1000);

  const frame: Frame = [];

  console.log();

  for (let height = 0; height < ROWS; height++) {
    const row: ModuleFrame[] = [];
    for (let lateral = 0; lateral < PER_ROW; lateral++) {
      row.push(module((edge, filament, end) => [0.0,0.2,0.2]));
    }
    frame.push(row);
  }



  //for(let x = 0; x < 5; x++)
    //for(let y = 0; y < 3; y++)
      for(let end of HexGridCoord.ends({
                      x: Math.floor(rand_period(now, 0, 200) * 14),
                      y: Math.floor(rand_period(now, 2, 200) * 3)
                    })) {
        const ef = end_frame(frame, end);
        const [top, btm] = EdgeRef.ends(end).map(r => end_frame(frame, r));

        top[0] = btm[0]

        for(let led of ef) {
          led[0] = 0
          led[1] = 0
          led[2] = 0
        }
        const c = 1//rand_period(now, 3, 400)
        console.log(c)
        let led = ef[0];//ef[Math.floor((rand_period(now, 5, 30) * 4) % 4)]
        led[0] = c
        led[1] = 0
        led[2] = 1-c
      }

  return frame;
}
