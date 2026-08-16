"""Python port of ts/lib/graph.ts — the module/edge/vertex connectivity graph.

Everything outside the app addresses LEDs in module/edge terms. This graph maps
between tiles, edges, ends and vertices so higher-level (hex) authoring can be
translated down to module edges.
"""
from __future__ import annotations

import math
from collections.abc import Generator, Iterable
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import ClassVar, Dict, Iterator, Tuple


class EdgeClass(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"


class VertexClass(StrEnum):
    ABF = "ABF"
    ABC = "ABC"
    CDE = "CDE"
    DEF = "DEF"


@dataclass(frozen=True)
class TileRef:
    x: int
    y: int

    # ClassVar so they aren't __init__ fields; the singletons are attached below.
    THIS: ClassVar["TileRef"]
    LEFT: ClassVar["TileRef"]
    RIGHT: ClassVar["TileRef"]
    UP: ClassVar["TileRef"]
    DOWN: ClassVar["TileRef"]

    WIDTH: ClassVar[float] = 1.0
    HEIGHT: ClassVar[float] = 1.732

    RADIUS: ClassVar[float] = 0.577

    # Location of the main hex center within a tile.
    ORIGIN_OFFSET_X: ClassVar[float] = 0.5
    ORIGIN_OFFSET_Y: ClassVar[float] = 2 * RADIUS

    @staticmethod
    def from_xy(x: int, y: int) -> "TileRef":
        return TileRef(x, y)

    @staticmethod
    def from_physical(x: float, y: float) -> "TileRef":
        """Inverse of physical(). Note the box it floors into is measured from
        the hex center, not the tile corner, so only exact centers round-trip."""
        return TileRef.from_xy(
            math.floor((x - TileRef.ORIGIN_OFFSET_X) / TileRef.WIDTH),
            math.floor((y - TileRef.ORIGIN_OFFSET_Y) / TileRef.HEIGHT),
        )

    def offset(self, a):
        """Translate any {tile: TileRef} ref by this tile's offset."""
        return replace(a, tile=a.tile.add(self))

    def negate(self) -> "TileRef":
        return TileRef(-self.x, -self.y)

    def add(self, tr: "TileRef") -> "TileRef":
        return TileRef(self.x + tr.x, self.y + tr.y)

    def edge(self, c: EdgeClass) -> "EdgeRef":
        return EdgeRef(c, self)

    def vertex(self, v: VertexClass) -> "VertexRef":
        return VertexRef(v, self)

    def top_end(self, c: EdgeClass) -> "EndRef":
        return EndRef(c, self, True)

    def bottom_end(self, c: EdgeClass) -> "EndRef":
        return EndRef(c, self, False)

    def physical(self) -> Tuple[float, float]:
        """Physical position of this tile's main hex center."""
        # A tile's origin is its main hex center, at (0.5, 0.577) within a tile
        # that is 1 wide and 1.732 high.
        return (self.x * TileRef.WIDTH + TileRef.ORIGIN_OFFSET_X,
                self.y * TileRef.HEIGHT + TileRef.ORIGIN_OFFSET_Y)


# dataclass turns the annotations above into fields; strip the constant markers
# and attach the real singletons.
for _name in ("THIS", "LEFT", "RIGHT", "UP", "DOWN"):
    TileRef.__dataclass_fields__.pop(_name, None)
TileRef.THIS = TileRef(0, 0)
TileRef.LEFT = TileRef(-1, 0)
TileRef.RIGHT = TileRef(1, 0)
TileRef.UP = TileRef(0, 1)
TileRef.DOWN = TileRef(0, -1)


@dataclass(frozen=True)
class VertexRef:
    vertex_class: VertexClass
    tile: TileRef

    def ends_cw(self) -> Tuple["EndRef", "EndRef", "EndRef"]:
        """Clockwise ends around the vertex; index 0 is always the vertical."""
        s = VERTEX_END_SETS[self.vertex_class]
        points_up = not s.v.top
        order = (s.v, s.r, s.l) if points_up else (s.v, s.l, s.r)
        return tuple(self.tile.offset(x) for x in order)  # type: ignore[return-value]

    def physical(self) -> Tuple[float, float]:
        """Physical position of this vertex."""
        cx, cy = self.tile.physical()          # center of the main hex
        ox, oy = TILE_VERTEX_OFFSETS[self.vertex_class]   # offset from center
        return (cx + ox, cy + oy)


@dataclass(frozen=True)
class EdgeRef:
    edge_class: EdgeClass
    tile: TileRef

    def ends(self) -> Tuple["EndRef", "EndRef"]:
        return (EndRef(self.edge_class, self.tile, True),
                EndRef(self.edge_class, self.tile, False))

    def vertex_pair(self) -> "EdgeVertexPair":
        p = EDGE_VERTEX_PAIRS[self.edge_class]
        return EdgeVertexPair(self.tile.offset(p.top), self.tile.offset(p.bottom))

@dataclass(frozen=True)
class FilamentRef:
    tile: TileRef
    idx: int
    first_end: EndRef

@dataclass(frozen=True)
class EndRef(EdgeRef):
    top: bool

    def other(self) -> "EndRef":
        return replace(self, top=not self.top)

    def vertex(self) -> VertexRef:
        vp = self.vertex_pair()
        return vp.top if self.top else vp.bottom

    def lr(self) -> Tuple["EndRef", "EndRef"]:
        cw = self.vertex().ends_cw()
        if cw[0].edge_class == self.edge_class:
            return (cw[1], cw[2])
        elif cw[1].edge_class == self.edge_class:
            return (cw[2], cw[0])
        else:
            return (cw[0], cw[1])
    
    def rotate(self, steps: int) -> EndRef:
        steps = steps % 3
        if steps == 0:
            return self
        else:
            return self.lr()[steps-1]

    def physical_to_next(self) -> Tuple[float, float]:
        """Vector pointing from this end to the opposite end of the edge."""
        fx, fy = self.vertex().physical()
        tx, ty = self.other().vertex().physical()
        return (tx - fx, ty - fy)
    
    def path(self, seq: Iterable[str]) -> Generator[EndRef, None, None]:
        # Starting at an end, navigate according to seq
        # Yields the first end of each edge visited
        # Empty 'seq' just gives a line
        current = self
        yield current
        for c in seq:
            current = current.other()
            lr = current.lr()
            match c:
                case "L":
                    current = lr[0]
                case "R":
                    current = lr[1]
            
            yield current


    def hex_ends(self) -> list[EndRef]:
        left = self.lr()[0]
        return list(left.path("R" * 5))

    def filament(self, idx: int) -> FilamentRef:
        return FilamentRef(self.tile, idx, first_end=self)


# An end is kind of also an 'edge with a direction'.

class TileGrid:
    def __getitem__(self, key: tuple[int, int]) -> TileRef:
        return TileRef(key[0], key[1])
TILE = TileGrid()

class VertexGrid:
    def __getitem__(self, key: tuple[int, int]) -> VertexRef:
        x,y = key
        # 4 rows per tile
        match (y % 4):
            case 0:
                return TileRef(x, y // 4).vertex(VertexClass.DEF)
            case 1:
                return TileRef(x, y // 4).vertex(VertexClass.CDE)
            case 2:
                return TileRef(x, y // 4).vertex(VertexClass.ABC)
            case _:
                return TileRef(x, y // 4).vertex(VertexClass.ABF)
            
VERTEX = VertexGrid()

@dataclass(frozen=True)
class EndSet:
    v: EndRef
    l: EndRef
    r: EndRef


@dataclass(frozen=True)
class EdgeVertexPair:
    top: VertexRef
    bottom: VertexRef


VERTEX_END_SETS: Dict[VertexClass, EndSet] = {
    VertexClass.ABC: EndSet(
        v=TileRef.THIS.top_end(EdgeClass.C),
        l=TileRef.LEFT.bottom_end(EdgeClass.B),
        r=TileRef.THIS.bottom_end(EdgeClass.A),
    ),
    VertexClass.ABF: EndSet(
        v=TileRef.UP.bottom_end(EdgeClass.F),
        l=TileRef.THIS.top_end(EdgeClass.A),
        r=TileRef.THIS.top_end(EdgeClass.B),
    ),
    VertexClass.CDE: EndSet(
        v=TileRef.THIS.bottom_end(EdgeClass.C),
        l=TileRef.LEFT.top_end(EdgeClass.E),
        r=TileRef.THIS.top_end(EdgeClass.D),
    ),
    VertexClass.DEF: EndSet(
        v=TileRef.THIS.top_end(EdgeClass.F),
        l=TileRef.THIS.bottom_end(EdgeClass.D),
        r=TileRef.THIS.bottom_end(EdgeClass.E),
    ),
}

# Vertex offsets from the main hex center. On a pointy-top hex the horizontal
# offset is RADIUS*sqrt(3)/2, which is half a tile width - not RADIUS itself.
TILE_VERTEX_OFFSETS: Dict[VertexClass, Tuple[float, float]] = {
    VertexClass.ABC: (-TileRef.WIDTH / 2, TileRef.RADIUS / 2),
    VertexClass.ABF: (0.0, TileRef.RADIUS),
    VertexClass.CDE: (-TileRef.WIDTH / 2, -TileRef.RADIUS / 2),
    VertexClass.DEF: (0.0, -TileRef.RADIUS),
}

EDGE_VERTEX_PAIRS: Dict[EdgeClass, EdgeVertexPair] = {
    EdgeClass.A: EdgeVertexPair(VertexRef(VertexClass.ABF, TileRef.THIS),
                                VertexRef(VertexClass.ABC, TileRef.THIS)),
    EdgeClass.B: EdgeVertexPair(VertexRef(VertexClass.ABF, TileRef.THIS),
                                VertexRef(VertexClass.ABC, TileRef.RIGHT)),
    EdgeClass.C: EdgeVertexPair(VertexRef(VertexClass.ABC, TileRef.THIS),
                                VertexRef(VertexClass.CDE, TileRef.THIS)),
    EdgeClass.D: EdgeVertexPair(VertexRef(VertexClass.CDE, TileRef.THIS),
                                VertexRef(VertexClass.DEF, TileRef.THIS)),
    EdgeClass.E: EdgeVertexPair(VertexRef(VertexClass.CDE, TileRef.RIGHT),
                                VertexRef(VertexClass.DEF, TileRef.THIS)),
    EdgeClass.F: EdgeVertexPair(VertexRef(VertexClass.DEF, TileRef.THIS),
                                VertexRef(VertexClass.ABF, TileRef.DOWN)),
}


# Working with the hex grid:

@dataclass(frozen=True)
class HexRef:
    # A precise hexagon is defined by a base vertex and an orientation - aka an end:
    base: EndRef        

    def ends(self) -> Iterable[EndRef]:
        return self.base.path("R" * 5)

    def rotate(self, steps: int) -> HexRef:
        # Rotate the hexagon clockwise some number of steps
        steps = steps % 6
        *_, last = self.base.path("R" * steps)
        return HexRef(base=last)
    
class HexGrid:
    def __getitem__(self, key: tuple[int, int]) -> HexRef:
        x,y = key
        if y % 2 == 0:
            vertex = TileRef(x, y // 2).vertex(VertexClass.DEF)
        else:
            vertex = TileRef(x + 1, y // 2).vertex(VertexClass.ABC)

        below = vertex.ends_cw()[0]     # top of the vertical below the vertex
        return HexRef(base=below.lr()[0])
HEX = HexGrid()
        

@dataclass(frozen=True)
class HexGridCoord:
    x: int
    y: int

    def ends(self) -> Iterator[EndRef]:
        """The 12 ends (top/bottom of each of 6 edges) around a hexagon."""
        if self.y % 2 == 0:
            vertex = TileRef(self.x, self.y // 2).vertex(VertexClass.DEF)
        else:
            vertex = TileRef(self.x + 1, self.y // 2).vertex(VertexClass.ABC)

        below = vertex.ends_cw()[0]     # top of the vertical below the vertex
        current = below.lr()[1]

        for _ in range(6):
            yield current
            current = current.other()
            yield current
            current = current.lr()[0]
