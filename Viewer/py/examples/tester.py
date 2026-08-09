"""Filament wiring/orientation tester.

On every module simultaneously, steps through each edge and lights its 4 filaments
one at a time, a second each. The lit filament runs white at its topmost end to
purple at its bottommost end — so you can read off filament order and top/bottom
orientation directly from the structure.

    1. python3 serve.py
    2. python3 py/examples/tester.py           # all edges, all modules
       python3 py/examples/tester.py A1        # just edge A1, all modules
       python3 py/examples/tester.py A1 0-5    # edge A1, module "0-5" (x-y = lateral-height)
       python3 py/examples/tester.py 0-5       # all edges, module "0-5"
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from py.lib import ModuleFrame, LatticeClient, EdgeClass, EdgeRef, TileRef   # noqa: E402

ROWS = 2          # stacked rings to cover
PER_ROW = 32      # modules per ring
FPS = 30

FILAMENTS = 4
WHITE = [1.0, 1.0, 1.0]
PURPLE = [0.5, 0.0, 1.0]

# A module's 12 edges, addressed via the graph: two tiles (x even/odd) x 6 edge
# classes. TileRef(x, 0).edge(class) is the EdgeRef; get_end_frame resolves it to
# the right ModuleEdge (…1 for tile 0, …2 for tile 1).
ALL_EDGES = [(TileRef(tx, 0).edge(ec), f"{ec.value}{tx + 1}")
             for tx in (0, 1) for ec in EdgeClass]


def build_frame(edges, step: int) -> ModuleFrame:
    """Blank frame with one (edge, filament) lit: top white, bottom purple."""
    mf = ModuleFrame.blank()
    edge, _name = edges[step // FILAMENTS]
    f = step % FILAMENTS
    top, bottom = EdgeRef.ends(edge)
    mf.get_end_frame(top)[f][:] = WHITE
    mf.get_end_frame(bottom)[f][:] = PURPLE
    return mf


def main() -> None:
    # Args (edge first, then module coord): an edge name A1..F2 and/or "x-y".
    edge_name = None
    module = None
    for a in sys.argv[1:]:
        if "-" in a:
            module = a
        else:
            edge_name = a.upper()

    if edge_name:
        edges = [e for e in ALL_EDGES if e[1] == edge_name]
        if not edges:
            sys.exit(f"unknown edge '{edge_name}' (expected A1..F2)")
    else:
        edges = ALL_EDGES

    if module:
        x, y = (int(v) for v in module.split("-"))       # "x-y" = lateral-height
        targets = [(x, y)]
        scope = f"module {module}"
    else:
        targets = [(l, h) for h in range(ROWS) for l in range(PER_ROW)]   # x=lateral, y=height
        scope = f"{ROWS}x{PER_ROW} modules"

    steps = len(edges) * FILAMENTS
    client = LatticeClient()
    print(f"tester: {steps} steps ({len(edges)} edge(s) x 4 filaments), 1s each, {scope}")

    start = time.monotonic()
    last_step = -1
    frame = build_frame(edges, 0)
    try:
        while True:
            step = int(time.monotonic() - start) % steps
            if step != last_step:
                last_step = step
                frame = build_frame(edges, step)
                _edge, name = edges[step // FILAMENTS]
                print(f"edge {name}  filament {step % FILAMENTS}  (top=white, bottom=purple)",
                      flush=True)
            for x, y in targets:
                client.sendModule(x, y, frame)
            time.sleep(1 / FPS)
    except KeyboardInterrupt:
        client.close()


if __name__ == "__main__":
    main()
