# pylattice

Python port of the Hex Lattice module libraries (see `ts/lib`).

```python
from pylattice import ModuleFrame, ModuleEdge, LatticeClient
```

| Module | Purpose |
| --- | --- |
| `frame` | One module's LED frame: 12 edges (A1..F2), each with a top/bottom end of 4 filament RGBs |
| `frame_format` | Packing a `ModuleFrame` into the 4-channel NeoPixel byte stream, and back |
| `graph` | Tile/edge/vertex connectivity, so hex-level authoring maps down to module edges |
| `lattice_client` | UDP multicast transport — one send reaches the viewer, tools and hardware |
| `lattice_writer` | Grid of module frames with a client attached |

Stdlib only, Python 3.11+. Install for development from this directory:

```sh
pip install -e .
```

Then run an example (with `serve.py` already running from the repo root):

```sh
python3 -m pylattice.examples.wave
```

The examples live in [`pylattice/examples/`](pylattice/examples) and ship with the package.
