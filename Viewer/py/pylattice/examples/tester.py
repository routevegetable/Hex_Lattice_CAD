"""Filament wiring/orientation tester.

On every module simultaneously, steps through each edge and lights its 4 filaments
one at a time, a second each. The lit filament runs white at its topmost end to
purple at its bottommost end — so you can read off filament order and top/bottom
orientation directly from the structure.

    1. python3 serve.py
    2. python3 -m pylattice.examples.tester           # all edges, all modules
       python3 -m pylattice.examples.tester A1        # just edge A1, all modules
       python3 -m pylattice.examples.tester C3        # the last module of a row's closing edge
       python3 -m pylattice.examples.tester A1 0-5    # edge A1, module "0-5" (x-y = lateral-height)
       python3 -m pylattice.examples.tester 0-5       # all edges, module "0-5"
"""

import sys
import time

from pylattice.graph import Graph
from pylattice.format import STANDARD_MODULE, WEIRD_TUBE
from pylattice import ModuleEdge, ModuleFrame, LatticeClient, TileRef
from pylattice.lattice_writer import LatticeWriter

ROWS = 2          # stacked rings to cover
PER_ROW = 32      # modules per ring
FPS = 2

FILAMENTS = 4
WHITE = [0, 1, 0]
PURPLE = [0, 0.0, 1]

graph = Graph(PER_ROW / 2, ROWS)

# A module's edges, A1..F2 and then C3.
ALL_EDGES = list(ModuleEdge)

"""
How do I rotate an end about a vertex.

If the end is defined as a path from that vertex, easy.

How about rotating about a hexagon.


Can I convert coordinates to paths.
LR is like going in one direction
"""

lattice = LatticeWriter(PER_ROW, ROWS)


def build_frame(edges, step: int) -> ModuleFrame:
    """Blank frame with one (edge, filament) lit: top white, bottom purple."""
    mf = ModuleFrame.blank()
    ends = mf[edges[step // (FILAMENTS * 2)]].ends
    f = step % FILAMENTS
    ends.top[f][:] = WHITE
    ends.bottom[f][:] = PURPLE
    return mf


tile = TileRef(graph, 0, 0)


def main() -> None:
    # Args (edge first, then module coord): an edge name A1..F2 or C3 and/or "x-y".
    edge_name = None
    module = None
    for a in sys.argv[1:]:
        if "-" in a:
            module = a
        else:
            edge_name = a.upper()

    if edge_name:
        edges = [e for e in ALL_EDGES if e.name == edge_name]
        if not edges:
            sys.exit(f"unknown edge '{edge_name}' (expected A1..F2 or C3)")
    else:
        edges = ALL_EDGES

    if module:
        x, y = (int(v) for v in module.split("-"))  # "x-y" = lateral-height
        targets = [(x, y)]
        scope = f"module {module}"
    else:
        targets = [
            (l, h) for h in range(ROWS) for l in range(PER_ROW)
        ]  # x=lateral, y=height
        scope = f"{ROWS}x{PER_ROW} modules"

    steps = len(edges) * FILAMENTS
    client = LatticeClient()
    print(
        f"tester: {steps} steps ({len(edges)} edge(s) x 4 filaments), 1s each, {scope}"
    )

    step = 0
    frame = build_frame(edges, 0)
    try:
        while True:
            step = (step + 1) % (len(edges) * FILAMENTS * 2)
            frame = build_frame(edges, step)
            name = edges[step // (FILAMENTS * 2)].name
            print(
                f"edge {name}  filament {step % FILAMENTS}  (top=white, bottom=purple)",
                flush=True,
            )
            for x, y in targets:
                data = STANDARD_MODULE.serialize(frame)
                client.send(x, y, data)

            time.sleep(1 / FPS)
    except KeyboardInterrupt:
        client.close()


if __name__ == "__main__":
    main()
