"""Python port of the Hinge Lattice module libraries (see ts/lib).

    from pylattice import ModuleFrame, ModuleEdge, LatticeClient
"""
from .frame import ModuleEdge, ModuleFrame, EdgeFrame, Ends
from .graph import (
    EdgeClass, VertexClass, TileRef, VertexRef, EdgeRef, EndRef, Graph
)
from .lattice_client import LatticeClient, DEFAULT_GROUP, DEFAULT_PORT, DEFAULT_IFACE

__all__ = [
    "ModuleEdge", "ModuleFrame", "EdgeFrame", "Ends",
    "EdgeClass", "VertexClass", "TileRef", "VertexRef", "EdgeRef", "EndRef",
    "Graph", "LatticeClient", "DEFAULT_GROUP", "DEFAULT_PORT", "DEFAULT_IFACE",
]
