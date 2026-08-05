// LED-controller emulator for the Hinge Hexagon installation.
//
// Runs under Deno as a SEPARATE process from the viewer. It generates a
// ModuleFrame per module and hands each to the frame sender (sender.ts), which
// datagrams it to the viewer's UNIX socket (created by serve.py). serve.py
// forwards each frame to the browser over a WebSocket, which routes it to the
// matching module and calls ModuleFrame.deserialize.
//
// Run (from ts/examples/, or `deno task app`):
//   deno run --allow-net --allow-env app.ts
// (--allow-net gates the unix datagram socket; --allow-env reads HINGE_SOCK.
//  "net" unstable is enabled via deno.json. Or just use -A.)
//
// Env:
//   HINGE_SOCK   server socket path (default /tmp/hinge-leds.sock)

import { ModuleFrame, EndFrame } from "../lib/frame.ts";
import { EdgeRef, EndRef, HexGridCoord } from "../lib/graph.ts";
import { LatticeClient } from "../lib/lattice-client.ts";

const ROWS = 2;          // stacked rings
const PER_ROW = 32;      // modules per ring
const FPS = 30;

let client = new LatticeClient();


const stop = () => { client.close(); Deno.exit(0); };
Deno.addSignalListener("SIGINT", stop);
Deno.addSignalListener("SIGTERM", stop);


type RGB = [number, number, number];
export type Frame = ModuleFrame[][];                     // frame[height][lateral]

function hsv(h: number, s: number, v: number): RGB {
  h = ((h % 1) + 1) % 1;
  const i = Math.floor(h * 6), f = h * 6 - i;
  const p = v * (1 - s), q = v * (1 - f * s), u = v * (1 - (1 - f) * s);
  switch (i % 6) {
    case 0: return [v, u, p]; case 1: return [q, v, p]; case 2: return [p, v, u];
    case 3: return [p, q, v]; case 4: return [u, p, v]; default: return [v, p, q];
  }
}


// Set of Modules

// Reused per-module buffers.
const buffers: ModuleFrame[][] = [];
for (let h = 0; h < ROWS; h++) {
  buffers[h] = [];
  for (let l = 0; l < PER_ROW; l++) buffers[h][l] = ModuleFrame.blank();
}

function end_frame(er: EndRef): EndFrame {
  const mf = buffers[er.tile.y][Math.floor(er.tile.x / 2)];
  return ModuleFrame.get_end_frame(mf, er);
}


console.log(`emulating ${ROWS}x${PER_ROW} modules @ ${FPS}fps`);


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
export function render(msec: number) {

  for(let end of HexGridCoord.ends({
    x: 0,
    y: 0
  })) {
    const ef = end_frame(end);
    for(let led of ef) {
        led[0] = 1
        led[1] = 0
        led[2] = 0
      }
  }
  //return

  const now = msec;

for(let i = 0; i < 4; i++)
    for(let end of HexGridCoord.ends({
                    x: Math.floor(rand_period(now+i*200, i, 600) * 14),
                    y: Math.floor(rand_period(now+i*200, i*10+2, 600) * 3)
                  })) {
      const ef = end_frame(end);
      const [top, btm] = EdgeRef.ends(end).map(r => end_frame(r));

      top[0] = btm[0]

      for(let led of ef) {
        led[0] = 0
        led[1] = 0
        led[2] = 0
      }
      const c = rand_period(now+i*200, i*10+3, 600)
      //console.log(c)
      let led = ef[i]; //ef[Math.floor((rand_period(now, 5, 70) * 3) % 4)]
      led[0] = c
      led[1] = c*0.5
      led[2] = 1-c
    }

}


let t = 0;

let busy = false
setInterval(async () => {

  if(busy == true) {
    // Last tick overran - skip this one
    return;
  }
  busy = true
  for (let h = 0; h < ROWS; h++) {
    buffers[h] = [];
    for (let l = 0; l < PER_ROW; l++) buffers[h][l] = ModuleFrame.blank();
  }

  render(Date.now());

  t += 1 / FPS;
  for (let h = 0; h < ROWS; h++) {
    for (let l = 0; l < PER_ROW; l++) {
      await client.sendModule(`${h}-${l}`, buffers[h][l]);
    }
  }
  busy = false
}, 1000 / FPS);
