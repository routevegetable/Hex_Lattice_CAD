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
import { MidiInterface } from "../lib/midi-clock.ts";

const ROWS = 2;          // stacked rings
const PER_ROW = 9;      // modules per ring
const FPS = 30;

// MIDI clock: read clock.beats / clock.bpm / clock.running in render() to sync
// visuals to an external tempo. Env MIDI_PORT = substring of the port to open.
const midi = new MidiInterface(Deno.env.get("MIDI_PORT") ?? undefined);




const CC3 = midi.get_cc(3);

/* At any time: */
const a: number = CC3.get_value()

midi.on_note((note, vel, on) => {

  console.log(note, vel, on)
  /* Do something */
})


let client = new LatticeClient();


const stop = () => { midi.close(); client.close(); Deno.exit(0); };
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
    wait = from;
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

function *random_seq(origin: EndRef, s: number): Generator<EndRef, void, void> {
  let current = origin;
  let l_last = false;
  let count = 0;
  while(true) {
    yield current;
    current = EndRef.other(current)
    yield current;

    let l_current = [
      false,
      true,
      !l_last
    ][Math.floor(hash(s + count) * 3) % 3];
    
    current = EndRef.lr(current)[l_current ? 0 : 1];
    l_last = l_current;
    count = count + 1;
  }
}


function burst(now: number, start: number, origin: EndRef, len: number) {

  const l = Math.floor(hash(start + 2) * 2) == 0;
  let sat = sweep(now, start, 300, 0, 1, 0);
  let value = sweep(now, start, 300, 3, 1, 1);
  //console.log(`sat:${sat} val:${value}`)
  let count = 0;
  for(let er of line_seq(origin, l)) {
    // For each end:
    try {
      const ef = end_frame(er)

      const end_start = start + count * 20;
      const b = sweep(now, end_start, 100, 1, 0, 0);

      //console.log(b)

      const c = hash(start)
      const filament = Math.floor((rand_period(now, start, 30) * 4) % 4);

      ef[filament] = hsv(c, sat, value * b);

    } catch {
      break;
    }
    if(count++ == len) {
      break;
    }
  }
}

const MAX_BURSTS = 40;
const bursts: [number, boolean][] = []
let last_burst: number = 0;

let now_time = 0;

let bool = true;

midi.on_beat(() => {
  bool = !bool;
  bursts.push([now_time, bool]);
  if(bursts.length > MAX_BURSTS) {
    bursts.shift()
  }
})



const STRING_HUES = [
  0.547,
  0.967,
  1
]

const STRING_TIME = 9000;

const STRING_COUNT = 8;


// 5 strings in flight at once
// string start period every second

// strings run for 5 seconds each

// strings in flight / string time = start interval
// string start period should be every 

// Make a pseudorandom end from s
function rand_end(s: number): EndRef {
  const x = Math.floor(hash(s * 10) * PER_ROW)
  const y = Math.floor(hash(s * 10 + 1) * ROWS)
  const e = [
    EdgeClass.A,
    EdgeClass.B,
    EdgeClass.C,
    EdgeClass.D,
    EdgeClass.E,
    EdgeClass.F
  ][Math.floor(hash(s * 10 + 3) * 6)];
  const bottom = Math.floor(hash(s * 10 + 4) * 2);

  const tile = new TileRef(x,y);

  return EdgeRef.ends(tile.edge(e))[bottom];
}

function rand_boundary_end(s: number): EndRef {
  const x = Math.floor(hash(s * 10) * PER_ROW * 2)
  const y = Math.floor(hash(s * 10 + 1) * 2)

  const e = [
    EdgeClass.A,
    EdgeClass.B,
    EdgeClass.C,
    EdgeClass.D,
    EdgeClass.E,
    EdgeClass.F
  ][Math.floor(hash(s * 10 + 3) * 6)];
  const bottom = Math.floor(hash(s * 10 + 4) * 2) == 0;

  if(bottom) {
    return new TileRef(x, 0).bottom_end(EdgeClass.F);
  } else {
    return new TileRef(x, ROWS-1).top_end(EdgeClass.A)
  }
}

function draw_strings(now: number) {

  const string_start_interval = STRING_TIME / STRING_COUNT;


  // Set up new strings
  for(let i = 0; i < STRING_COUNT; i++) {
    const hue = STRING_HUES[i % 3]
    const start_time = periodic(now - i * string_start_interval, STRING_TIME) + i * string_start_interval;
    //console.log(start_time)
    const origin = rand_boundary_end(start_time + i);

    let count = 0;
    for(let er of random_seq(origin, start_time + i)) {
      // For each end:

      const dt = count * 35;
      const end_start = start_time + dt;

      let ef;
      try {
        ef = end_frame(er)
      } catch(e) {
        break;
      }

      const b = sweep(now, end_start, 40, 0, 1, 0);
      const b2 = sweep(now, (end_start + STRING_TIME)-1000, 40, 1, 0, 1);

      const flash_period = periodic(now - i * string_start_interval, 2000) + i * string_start_interval;
      const flash_env = Math.sin(sweep(now, flash_period + dt, 1000, 0, 3.141, 3.141)) * 0.75;
      //if(i == 1 && count == 0) console.log(flash_env.toFixed(2))
      const hue_dev = sweep(now, end_start, STRING_TIME, hue-0.05, hue+0.05)

      //console.log(i, count, origin, er)

      if(false && i == 1 && count == 0)
        console.log(count, now, start_time, end_start, b*b2)

      //if(i == 1 && count == 6) console.log(count, now, end_start, b*b2)
      //if(i == 1 && count == 7) console.log(count, now, end_start, b*b2)

      //if(i == 0) console.log(count)

      ef[i % 4] = hsv(hue_dev, 1-flash_env, b*b2);

      if(count++ == 100) {
        break;
      }
    }
  }
}

// --- the render function ---------------------------------------------------
// Called every frame with the time in seconds. Edit freely and save — it live
// reloads. Default: a per-edge hue with a wave travelling down each strand.
export function render(msec: number) {

  now_time = msec;

  for(let end of HexGridCoord.ends({
    x: 0,
    y: 0
  })) {
    const ef = end_frame(end);
    for(let led of ef) {
        led[0] = 0
        led[1] = 0
        led[2] = 0
      }
  }

  const GAP = 30; // between bursts

/*   const b = periodic(msec, GAP)
  if(b > last_burst) {
    last_burst = b;
    bursts.push(last_burst);
    if(bursts.length > MAX_BURSTS) {
      bursts.shift()
    }
  } */

  for(let b of bursts) {
    const [start_time, t] = b;
    const e = [
      EdgeClass.A,
      EdgeClass.B,
      EdgeClass.C,
      EdgeClass.D,
      EdgeClass.E,
      EdgeClass.F
    ][Math.floor(hash(start_time + 3) * 6)];
    const bottom = Math.floor(hash(start_time + 4) * 2) == 0;


    if(t) {
      const x = 1 + Math.floor(hash(start_time) * 14)
      const y = 1;//Math.floor(hash(start_time + 1) * 3)
      const tile = new TileRef(x,y);
      //console.log(msec, start_time)

      const v = EndRef.vertex(tile.top_end(EdgeClass.F))
      let off = 0;
      for(let e of VertexRef.ends_cw(v)) {
        burst(msec, start_time, e, 16)
        off = off + 1;
      }
    } else {
      const x = 1 + Math.floor(hash(start_time) * 14)
      const y = 0;//Math.floor(hash(start_time + 1) * 3)
      const tile = new TileRef(x,y);
      burst(msec, start_time, tile.bottom_end(EdgeClass.F), 16)
    }
  }

  //draw_strings(msec);

  return;
  const now = msec;

for(let i = 0; i < 2; i++)
    for(let end of HexGridCoord.ends({
                    x: Math.floor(rand_period(now+i*100, i, 200) * 20),
                    y: Math.floor(rand_period(now+i*100, i*10+2, 200) * 3)
                  })) {

      let ef;
      try {
        ef = end_frame(end);
      } catch {
        continue;
      }
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

let st = Date.now();

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

  render(Date.now() - st);

  t += 1 / FPS;
  for (let h = 0; h < ROWS; h++) {
    for (let l = 0; l < PER_ROW; l++) {
      await client.sendModule(l, h, buffers[h][l]);   // x=lateral, y=height
    }
  }
  busy = false
}, 1000 / FPS);
