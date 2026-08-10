"""Example: port of the CircuitPython rig's four_colors() look (program.py on
the board) to the lattice simulation.

Steps through red/green/blue/purple, one filament index at a time (1s lit +
1s dark each, looping), each lit filament's top end getting its color and
bottom end going white. On the physical rig this is pixel_pairs.set(i, ...)
called with edge=None, which broadcasts to every one of the board's 6 wired
edges at once; there's no per-edge or per-module variation to port, so this
does the same thing — one ModuleFrame computed per tick, sent unchanged to
every module's every edge (A1..F2).

    1. python3 serve.py                 # creates the socket + serves the viewer
    2. python3 py/examples/four_colors.py

Env: HINGE_SOCK overrides the socket path (LatticeClient resolves it).
"""
import os
import sys
import time

# Make the repo root importable so `py.lib` resolves.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from py.lib import ModuleFrame, LatticeClient   # noqa: E402

ROWS = 2          # stacked rings
PER_ROW = 32      # modules per ring
FPS = 30

# same colors as colors.py on the rig
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
WHITE = (80, 80, 80)
PURPLE = (128, 0, 128)

COLORS = [RED, GREEN, BLUE, PURPLE]
PERIOD = 2.0                      # 1s lit + 1s dark per color
TOTAL = PERIOD * len(COLORS)


def _unit(col):
    # hardware colors are 0-255 ints; ModuleFrame wants 0-1 floats
    return [c / 255 for c in col]


def paint(mf: ModuleFrame, t: float) -> None:
    active = int((t % TOTAL) // PERIOD)
    lit = (t % PERIOD) < 1.0
    for e in range(12):
        edge = mf[e]
        for f in range(len(COLORS)):
            if f == active and lit:
                edge.ends.top[f][:] = _unit(COLORS[f])
                edge.ends.bottom[f][:] = _unit(WHITE)
            else:
                edge.ends.top[f][:] = [0.0, 0.0, 0.0]
                edge.ends.bottom[f][:] = [0.0, 0.0, 0.0]


class Pixels:
    """List-like wrapper around a channel-0 pixel buffer, with show() to push it."""

    def __init__(self, client: LatticeClient, count: int, x: int = 0, y: int = 0):
        self._client = client
        self._x = x
        self._y = y
        self._data = [(0, 0, 0)] * count

    def __len__(self) -> int:
        return len(self._data)

    def __getitem__(self, i):
        return self._data[i]

    def __setitem__(self, i, value) -> None:
        self._data[i] = list(value)

    def show(self) -> None:
        self._client.sendChannels(self._x, self._y, [self._data, [], [], []])



# client = LatticeClient()
# pixels = Pixels(client, 48)

# pixels[0] = (255, 0, 255)
# pixels.show()
# while True:
#     ...




def main() -> None:
    client = LatticeClient()      # socket path from HINGE_SOCK / default
    mf = ModuleFrame.blank()
    print(f"four_colors: broadcasting to {ROWS}x{PER_ROW} modules @ {FPS}fps")
    t = 0.0
    try:
        while True:
            t += 1 / FPS
            paint(mf, t)
            for h in range(ROWS):
                for l in range(PER_ROW):
                    #client.sendModule(l, h, mf)

                    client.sendChannels(0,0,[
                        [(255,255,255)]*64,
                        [],
                        [],
                        []
                        ])
            time.sleep(1 / FPS)
    except KeyboardInterrupt:
        client.close()


if __name__ == "__main__":
    main()
