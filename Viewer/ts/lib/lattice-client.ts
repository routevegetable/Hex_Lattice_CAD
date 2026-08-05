// The client that sends module frames to the lattice (the LED hardware, emulated
// by serve.py's UNIX socket). This is the transport only — callers own the render
// logic and just hand it a location + ModuleFrame.
//
// Each frame is one datagram:
//   [1 byte: length of location][location ascii, e.g. "0-0"][ModuleFrame.serialize]

import { ModuleFrame } from "./frame.ts";

export const DEFAULT_SOCK = "/tmp/hinge-leds.sock";

// Length-prefixed ("pascal") string: [1 byte length][utf-8 bytes].
function pascal(s: string): Uint8Array {
  const b = new TextEncoder().encode(s);
  const out = new Uint8Array(1 + b.length);
  out[0] = b.length;
  out.set(b, 1);
  return out;
}

export class LatticeClient {
  private readonly serverSock: string;
  private readonly conn: Deno.DatagramConn;
  private warned = false;

  // Socket path: explicit arg > HINGE_SOCK env > default.
  constructor(serverSock?: string) {
    this.serverSock = serverSock ?? Deno.env.get("HINGE_SOCK") ?? DEFAULT_SOCK;
    // No `path` => the datagram socket autobinds to an anonymous address (no
    // socket file on disk). We only ever send from it, never receive. Deno's
    // types insist on a path for unixpacket, but omitting it is valid at runtime.
    // deno-lint-ignore no-explicit-any
    this.conn = Deno.listenDatagram({ transport: "unixpacket" } as any);
  }

  /** Send one module's frame, addressed to `location` (e.g. "0-0" = height-lateral). */
  async sendModule(location: string, frame: ModuleFrame): Promise<void> {
    const loc = pascal(location);
    const payload = ModuleFrame.serialize(frame);
    const msg = new Uint8Array(loc.length + payload.length);
    msg.set(loc);
    msg.set(payload, loc.length);
    try {
      await this.conn.send(msg, { path: this.serverSock, transport: "unixpacket" });
      this.warned = false;
    } catch (e) {
      if (!this.warned) { this.warned = true; console.error(`send failed (is serve.py running?): ${e}`); }
    }
  }

  /** Close the socket. */
  close(): void {
    try { this.conn.close(); } catch { /* ignore */ }
  }
}
