// MIDI input interface for a render loop. Wraps clock/transport, per-beat and
// note callbacks, and CC value polling:
//   midi.beats / midi.bpm / midi.running   transport state (24 PPQN clock)
//   midi.on_beat(cb)                        cb(beat) once per quarter-note
//   midi.on_note(cb)                        cb(note, velocity, on) on note on/off
//   midi.get_cc(n)                          handle; .get_value() = latest 0-127
//
// Uses npm:@julusian/midi (a native addon → CoreMIDI on macOS), so Deno needs
// broad perms — run with `-A`. Fails soft (logs, stays inert) if MIDI is
// unavailable, so callers can fall back to a wall clock.

import midi from "npm:@julusian/midi";

const PPQN = 24;   // MIDI clock pulses per quarter-note

/** A handle to one CC controller; get_value() returns its latest value (0-127). */
export type CC = { get_value(): number };

type BeatCb = (beat: number) => void;
type NoteCb = (note: number, velocity: number, on: boolean) => void;

export class MidiInterface {
  beats = 0;             // quarter-notes elapsed since the last Start
  bpm = 120;             // smoothed, estimated from clock-pulse spacing
  running = false;

  private input: midi.Input | null = null;
  private pulses = 0;
  private lastPulse = 0;
  private lastBeat = -1;
  private beatCbs: BeatCb[] = [];
  private noteCbs: NoteCb[] = [];
  private ccValues = new Map<number, number>();
  private ccObjs = new Map<number, CC>();

  /** Opens the first input port, or one whose name contains `portMatch`. */
  constructor(portMatch?: string) {
    try {
      const input = new midi.Input();
      const count = input.getPortCount();
      let port = -1;
      for (let i = 0; i < count; i++) {
        const name = input.getPortName(i);
        console.log(`MIDI in [${i}]: ${name}`);
        if (port < 0 && (!portMatch || name.toLowerCase().includes(portMatch.toLowerCase()))) port = i;
      }
      if (port < 0) { console.warn("MIDI: no input port found"); return; }
      input.ignoreTypes(true, false, true);        // keep TIMING (clock); ignore sysex/active-sense
      input.on("message", (_dt: number, msg: number[]) => this.onMessage(msg));
      input.openPort(port);
      this.input = input;
      console.log(`MIDI: listening on "${input.getPortName(port)}"`);
    } catch (e) {
      console.warn(`MIDI: unavailable (${e})`);
    }
  }

  /** Fired once per quarter-note beat, with the (integer) beat index. */
  on_beat(cb: BeatCb): void { this.beatCbs.push(cb); }

  /** Fired on note-on and note-off, with note number, velocity and an on flag. */
  on_note(cb: NoteCb): void { this.noteCbs.push(cb); }

  /** A stable handle for controller `n`; .get_value() reflects the latest CC value. */
  get_cc(n: number): CC {
    let cc = this.ccObjs.get(n);
    if (!cc) {
      cc = { get_value: () => this.ccValues.get(n) ?? 0 };
      this.ccObjs.set(n, cc);
    }
    return cc;
  }

  close(): void { try { this.input?.closePort(); } catch { /* ignore */ } }

  private onMessage(msg: number[]): void {
    const status = msg[0];
    if (status >= 0xF8) { this.onRealtime(status); return; }   // system real-time
    switch (status & 0xF0) {
      case 0x90:                                                // note on (velocity 0 = off)
        this.fireNote(msg[1], msg[2], msg[2] > 0);
        break;
      case 0x80: this.fireNote(msg[1], msg[2], false); break;   // note off
      case 0xB0: this.ccValues.set(msg[1], msg[2]); break;      // control change
    }
  }

  private onRealtime(status: number): void {
    switch (status) {
      case 0xFA:                                    // Start
        this.running = true; this.pulses = 0; this.beats = 0; this.lastBeat = -1; this.lastPulse = 0;
        console.log("MIDI: start");
        break;
      case 0xFB: this.running = true; break;        // Continue
      case 0xFC:                                     // Stop
        this.running = false;
        console.log(`MIDI: stop @ ${this.beats.toFixed(2)} beats`);
        break;
      case 0xF8: {                                   // Clock pulse (24 per quarter-note)
        if (!this.running) break;
        this.pulses++;
        this.beats = this.pulses / PPQN;
        const beat = Math.floor(this.beats);
        if (beat !== this.lastBeat) { this.lastBeat = beat; this.fireBeat(beat); }
        const t = performance.now();
        if (this.lastPulse) {
          const inst = 60000 / ((t - this.lastPulse) * PPQN);   // BPM from this interval
          if (isFinite(inst) && inst > 20 && inst < 400) this.bpm = this.bpm * 0.9 + inst * 0.1;
        }
        this.lastPulse = t;
        break;
      }
    }
  }

  private fireBeat(beat: number): void {
    for (const cb of this.beatCbs) { try { cb(beat); } catch (e) { console.error(e); } }
  }

  private fireNote(note: number, velocity: number, on: boolean): void {
    for (const cb of this.noteCbs) { try { cb(note, velocity, on); } catch (e) { console.error(e); } }
  }
}
