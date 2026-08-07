// LED-controller emulator for the Hinge Hexagon installation.
//
// Runs under Deno as a SEPARATE process from the viewer. It generates a
// ModuleFrame per module and hands each to the frame sender (sender.ts), which
// datagrams it to the viewer's UNIX socket (created by serve.py). serve.py
// forwards each frame to the browser over a WebSocket, which routes it to the
// matching module and calls ModuleFrame.deserialize.
//
// Run (from ts/examples/, or `deno task app`):
//   deno run --allow-net --allow-write --allow-env app.ts
// (--allow-net creates the unix datagram socket, --allow-write sends to the
//  server socket path, --allow-env reads HINGE_SOCK. "net" unstable comes from
//  deno.json. Or just use -A.)
//
// Env:
//   HINGE_SOCK   server socket path (default /tmp/hinge-leds.sock)

import { EdgeClass, TileRef, VertexClass, VertexRef } from "./../lib/graph.ts";
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

// Random number
function rand_period(now: number, salt: number, period_ms: number): number {
  return hash(Math.floor(now / period_ms) + salt)
}

// Linear sweep
function sweep(now: number, start: number, period_ms: number, from: number = 0, to: number = 1, wait: number | null = null): number {
  if(wait === null) {
    wait = start;
  }
  if(now < start) {
    return wait;
  }
  if(now >= (start + period_ms)) {
    return to;
  }

  const dt = (now - start) / period_ms;
  const dv = to - from;
  return from + dt * dv;
}

// Periodic event
function periodic(now: number, period_ms: number): number {
  return Math.floor(now / period_ms) * period_ms;
}

// Periodic sweep
function psweep(now: number, period_ms: number, from: number = 0, to: number = 1): number {
  return sweep(now, periodic(now, period_ms), period_ms, from, to)
}

function *line_seq(origin: EndRef, l: boolean): Generator<EndRef, void, void> {
  let current = origin;
  let lcurrent = l;
  while(true) {
    yield current;
    current = EndRef.other(current)
    yield current;
    current = EndRef.lr(current)[lcurrent ? 0 : 1];
    lcurrent = !lcurrent;
  }
}


function burst(now: number, start: number, origin: EndRef) {

  console.log(origin)
  let count = 0;
  for(let er of line_seq(origin, true)) {
    try {
      const ef = end_frame(er)
      const b = sweep(now, start + count * 30, 300, 1, 0, 0);
      console.log(b)

      const c = hash(start)
      //console.log(c)
      let led = ef[Math.floor((rand_period(now, 5, 70) * 3) % 4)]
        led[0] = b * 0.8
        led[1] = hash(start+2) * b * 0.5
        led[2] = b

      //let col:RGB = [b,b,b]

      //for(let i = 0; i < 4; i++) {
        //ef[i] = col;
      //}
    } catch {
      break;
    }
    if(count++ == 13) {
      break;
    }
  }
}

const MAX_BURSTS = 40;
const bursts: number[] = []
let last_burst: number = 0;

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
        led[0] = 0
        led[1] = 1
        led[2] = 1
      }
  }
  //

  const GAP = 50; // between bursts

  const b = periodic(msec, GAP)
  if(b > last_burst) {
    last_burst = b;
    bursts.push(last_burst);
    if(bursts.length > MAX_BURSTS) {
      bursts.shift()
    }
  }

  for(let start_time of bursts) {
    const x = Math.floor(hash(start_time) * 30)
    const y = Math.floor(hash(start_time + 1) * 3)
    const l = Math.floor(hash(start_time + 2) * 2) == 0;
    const e = [
      EdgeClass.A,
      EdgeClass.B,
      EdgeClass.C,
      EdgeClass.D,
      EdgeClass.E,
      EdgeClass.F
    ][Math.floor(hash(start_time + 3) * 6)];
    const bottom = Math.floor(hash(start_time + 4) * 2) == 0;

    const tile = new TileRef(x,y);
    console.log(start_time)

    burst(msec, start_time, bottom ? tile.bottom_end(e) : tile.top_end(e))
  }
  const now = msec;

for(let i = 0; i < 2; i++)
    for(let end of HexGridCoord.ends({
                    x: Math.floor(rand_period(now+i*100, i, 200) * 14),
                    y: Math.floor(rand_period(now+i*100, i*10+2, 200) * 3)
                  })) {
      const ef = end_frame(end);
      const [top, btm] = EdgeRef.ends(end).map(r => end_frame(r));


      for(let led of ef) {
        led[0] = 0
        led[1] = 0
        led[2] = 0
      }
      const c = rand_period(now+i*100, i*10+3, 10)
      //console.log(c)
      let led = ef[Math.floor((rand_period(now, 5, 70) * 3) % 4)]
        led[0] = 1
        led[1] = c
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
