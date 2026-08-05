"""Example: drive the lattice with a travelling hue wave (Python).

    1. python3 serve.py                 # creates the socket + serves the viewer
    2. python3 py/examples/wave.py

Env: HINGE_SOCK overrides the socket path (LatticeClient resolves it).
"""
import math
import os
import sys
import time

# Make the repo root importable so `py.lib` resolves.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from py.lib import ModuleFrame, LatticeClient, ModuleEdge   # noqa: E402

ROWS = 2          # stacked rings
PER_ROW = 32      # modules per ring
FPS = 30


def hsv(h: float, s: float, v: float):
    h = (h % 1 + 1) % 1
    i = int(h * 6)
    f = h * 6 - i
    p, q, u = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    return [(v, u, p), (q, v, p), (p, v, u), (p, q, v), (u, p, v), (v, p, q)][i % 6]


def paint(mf: ModuleFrame, t: float, h: int, l: int) -> None:
    for e in range(12):
        edge = mf[e]
        hue = (e / 12 + l * 0.03 + h * 0.12 + t * 0.1) % 1
        for f in range(4):
            top = hsv(hue, 1, 0.5 + 0.5 * math.sin(t * 2 - e * 0.4 - f * 0.25 + l * 0.5))
            btm = hsv(hue, 1, 0.5 + 0.5 * math.sin(t * 2 - e * 0.4 - f * 0.25 + l * 0.5 - 0.9))
            edge.ends.top[f][:] = list(top)
            edge.ends.bottom[f][:] = list(btm)


def main() -> None:
    client = LatticeClient()      # socket path from HINGE_SOCK / default
    buffers = [[ModuleFrame.blank() for _ in range(PER_ROW)] for _ in range(ROWS)]
    print(f"wave: {ROWS}x{PER_ROW} modules @ {FPS}fps")
    t = 0.0
    try:
        while True:
            t += 1 / FPS
            for h in range(ROWS):
                for l in range(PER_ROW):
                    paint(buffers[h][l], t, h, l)
                    client.sendModule(f"{h}-{l}", buffers[h][l])
            time.sleep(1 / FPS)
    except KeyboardInterrupt:
        client.close()


if __name__ == "__main__":
    main()
