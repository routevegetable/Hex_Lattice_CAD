// Example: drive the lattice with a travelling hue wave (TypeScript / Deno).
//
//   1. python3 serve.py                       # creates the socket + serves the viewer
//   2. deno run --unstable-net -A ts/examples/wave.ts
//
// Env: HINGE_SOCK overrides the socket path (LatticeClient resolves it).

import { ModuleEdge, ModuleFrame } from "../lib/frame.ts";
import { LatticeClient } from "../lib/lattice-client.ts";

const ROWS = 2;          // stacked rings
const PER_ROW = 32;      // modules per ring
const FPS = 30;

type RGB = [number, number, number];

function hsv(h: number, s: number, v: number): RGB {
  h = ((h % 1) + 1) % 1;
  const i = Math.floor(h * 6), f = h * 6 - i;
  const p = v * (1 - s), q = v * (1 - f * s), u = v * (1 - (1 - f) * s);
  switch (i % 6) {
    case 0: return [v, u, p]; case 1: return [q, v, p]; case 2: return [p, v, u];
    case 3: return [p, q, v]; case 4: return [u, p, v]; default: return [v, p, q];
  }
}

// A per-edge hue with a wave travelling down each strand (top -> bottom gradient).
function paint(mf: ModuleFrame, t: number, h: number, l: number): void {
  for (let e = 0; e < 12; e++) {
    const edge = mf[e as ModuleEdge];
    const hue = (e / 12 + l * 0.03 + h * 0.12 + t * 0.1) % 1;
    for (let f = 0; f < 4; f++) {
      const top = hsv(hue, 1, 0.5 + 0.5 * Math.sin(t * 2 - e * 0.4 - f * 0.25 + l * 0.5));
      const btm = hsv(hue, 1, 0.5 + 0.5 * Math.sin(t * 2 - e * 0.4 - f * 0.25 + l * 0.5 - 0.9));
      const et = edge.ends.top[f], eb = edge.ends.bottom[f];
      et[0] = top[0]; et[1] = top[1]; et[2] = top[2];
      eb[0] = btm[0]; eb[1] = btm[1]; eb[2] = btm[2];
    }
  }
}

const client = new LatticeClient();     // socket path from HINGE_SOCK / default
Deno.addSignalListener("SIGINT", () => { client.close(); Deno.exit(0); });
console.log(`wave: ${ROWS}x${PER_ROW} modules @ ${FPS}fps`);

const buffers: ModuleFrame[][] = [];
for (let h = 0; h < ROWS; h++) {
  buffers[h] = [];
  for (let l = 0; l < PER_ROW; l++) buffers[h][l] = ModuleFrame.blank();
}


let t = 0;
setInterval(async () => {
  t += 1 / FPS;
  const sends: Promise<void>[] = [];
  for (let h = 0; h < ROWS; h++) {
    for (let l = 0; l < PER_ROW; l++) {
      paint(buffers[h][l], t, h, l);
      sends.push(client.sendModule(l, h, buffers[h][l]));   // x=lateral, y=height
    }
  }
  await Promise.all(sends);
}, 1000 / FPS);
