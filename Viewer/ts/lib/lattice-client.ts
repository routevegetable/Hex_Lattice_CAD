// The client that sends module frames to the lattice (the LED hardware, and the
// viewer via serve.py). Transport is UDP multicast — one send is delivered to
// every local consumer that has joined the group (serve.py, other tools, real
// hardware). Callers own the render logic and just hand it a location + frame.
//
// Each frame is one datagram:
//   [1 byte: length of location][location ascii, e.g. "0-0"][ModuleFrame.serialize]

import { ModuleFrame } from "./frame.ts";

export const DEFAULT_GROUP = "239.69.69.69";   // administratively-scoped (RFC 2365)
export const DEFAULT_PORT = 6969;
export const DEFAULT_IFACE = "127.0.0.1";      // egress interface (loopback = stay local)

// Length-prefixed ("pascal") string: [1 byte length][utf-8 bytes].
function pascal(s: string): Uint8Array {
  const b = new TextEncoder().encode(s);
  const out = new Uint8Array(1 + b.length);
  out[0] = b.length;
  out.set(b, 1);
  return out;
}

export class LatticeClient {
  private readonly group: string;
  private readonly port: number;
  private readonly conn: Deno.DatagramConn;
  private readonly ready: Promise<void>;
  private warned = false;

  // group/port/iface: explicit arg > HEXNET_MCAST_* env > default.
  constructor(group?: string, port?: number, iface?: string) {
    this.group = group ?? Deno.env.get("HEXNET_MCAST_GROUP") ?? DEFAULT_GROUP;
    this.port = port ?? (Number(Deno.env.get("HEXNET_MCAST_PORT")) || DEFAULT_PORT);
    const ifc = iface ?? Deno.env.get("HEXNET_MCAST_IF") ?? DEFAULT_IFACE;
    const conn = Deno.listenDatagram({ transport: "udp", hostname: "0.0.0.0", port: 0 });
    this.conn = conn;
    const grp = this.group;
    // Joining on `ifc` pins the send to that interface (loopback keeps it on the
    // box; Deno has no direct IP_MULTICAST_IF setter). setLoopback keeps a copy
    // for local receivers. sendModule awaits this before its first send.
    this.ready = (async () => {
      try {
        const m = await conn.joinMulticastV4(grp, ifc);
        m.setLoopback(true);
      } catch (e) {
        console.error(`multicast join failed (${grp} on ${ifc}): ${e}`);
      }
    })();
  }

  /** Send one module's frame, addressed by grid coords x (lateral) and y (height). */
  async sendModule(x: number, y: number, frame: ModuleFrame): Promise<void> {
    await this.ready;
    const loc = pascal(`${x}-${y}`);
    const payload = ModuleFrame.serialize(frame);
    const msg = new Uint8Array(loc.length + payload.length);
    msg.set(loc);
    msg.set(payload, loc.length);
    try {
      await this.conn.send(msg, { transport: "udp", hostname: this.group, port: this.port });
      this.warned = false;
    } catch (e) {
      if (!this.warned) { this.warned = true; console.error(`send failed: ${e}`); }
    }
  }

  /** Close the socket. */
  close(): void {
    try { this.conn.close(); } catch { /* ignore */ }
  }
}
