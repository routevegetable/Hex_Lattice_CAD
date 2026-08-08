export enum EdgeClass {
    A = "A",
    B = "B",
    C = "C",
    D = "D",
    E = "E",
    F = "F"
}

export enum VertexClass {
    ABF = "ABF",
    ABC = "ABC",
    CDE = "CDE",
    DEF = "DEF"
}

export class TileRef {

    constructor(
        public x: number,
        public y: number) { }

    static readonly THIS = new TileRef(0, 0);
    static readonly LEFT = new TileRef(-1, 0);
    static readonly RIGHT = new TileRef(1, 0);
    static readonly UP = new TileRef(0, 1);
    static readonly DOWN = new TileRef(0, -1);

    static readonly WIDTH = 1;
    static readonly HEIGHT = 1.732;

    static readonly RADIUS = 0.577;

    /* Location of main hex center within a tile: */

    static readonly ORIGIN_OFFSET_X = 0.5;
    static readonly ORIGIN_OFFSET_Y = 2 * TileRef.RADIUS;


    static from(x: number, y: number) {
        return new TileRef(
            x,y
        )
    }

    static from_physical(x: number, y: number) {

        return TileRef.from(
            Math.floor((x - TileRef.ORIGIN_OFFSET_X) / TileRef.WIDTH),
            Math.floor((y - TileRef.ORIGIN_OFFSET_Y) / TileRef.HEIGHT)
        )
    }

    offset<const T extends { tile: TileRef }>(a: T): T {
        const b = { ...a };
        b.tile = b.tile.add(this);
        return b;
    }

    negate(): TileRef {
        return new TileRef(
            -this.x,
            -this.y
        )
    }

    add(tr: TileRef): TileRef {
        return new TileRef(
            this.x + tr.x,
            this.y + tr.y
        )
    }

    edge(c: EdgeClass): EdgeRef {
        return {
            edge_class: c,
            tile: this
        }
    }

    vertex(v: VertexClass): VertexRef {
        return {
            tile: this,
            vertex_class: v
        };
    }

    top_end(c: EdgeClass): EndRef {
        return {
            edge_class: c, tile: this,
            top: true
        }
    }

    bottom_end(c: EdgeClass): EndRef {
        return {
            edge_class: c, tile: this,
            top: false
        }
    }

    physical(): [number, number] {
        // Origin of a tile is at the main hex center point, which is at 0.5, 0.577
        // Width of a tile is '1'
        // Height of a tile is 1.732
        return [this.x * TileRef.WIDTH + TileRef.ORIGIN_OFFSET_X,
                this.y * TileRef.HEIGHT + TileRef.ORIGIN_OFFSET_Y]

    }
}
export type VertexRef = {
    vertex_class: VertexClass
    tile: TileRef
}

export type EdgeRef = {
    edge_class: EdgeClass
    tile: TileRef
}

export type EndRef = {
    top: boolean,
} & EdgeRef



// A vertex class has a number of endrefs
export type EndSet = {
    v: EndRef,
    l: EndRef,
    r: EndRef,
}


const VERTEX_END_SETS: { [key in VertexClass]: EndSet } = {
    [VertexClass.ABC]: {
        v: TileRef.THIS.top_end(EdgeClass.C),
        l: TileRef.LEFT.bottom_end(EdgeClass.B),
        r: TileRef.THIS.bottom_end(EdgeClass.A)
    }, [VertexClass.ABF]: {
        v: TileRef.UP.bottom_end(EdgeClass.F),
        l: TileRef.THIS.top_end(EdgeClass.A),
        r: TileRef.THIS.top_end(EdgeClass.B)
    }, [VertexClass.CDE]: {
        v: TileRef.THIS.bottom_end(EdgeClass.C),
        l: TileRef.LEFT.top_end(EdgeClass.E),
        r: TileRef.THIS.top_end(EdgeClass.D)
    }, [VertexClass.DEF]: {
        v: TileRef.THIS.top_end(EdgeClass.F),
        l: TileRef.THIS.bottom_end(EdgeClass.D),
        r: TileRef.THIS.bottom_end(EdgeClass.E)
    }
}


export const VertexRef = {
    // clockwise ends. 0 is always the vertical.
    ends_cw(v: VertexRef): [EndRef, EndRef, EndRef] {
        const set = VERTEX_END_SETS[v.vertex_class];

        const points_up = !set.v.top;

        return (points_up ? [
            set.v,
            set.r,
            set.l
        ] : [
            set.v,
            set.l,
            set.r
        ]).map(x => v.tile.offset(x)) as [EndRef, EndRef, EndRef];
    },

    // Physical location
    physical(v: VertexRef): [number, number] {

        // Center of main hex
        const center_pos = v.tile.physical();

        // Offsets from center
        const offs = TILE_VERTEX_OFFSETS[v.vertex_class];

        return [
            center_pos[0] + offs[0],
            center_pos[1] + offs[1]
        ]
    }
}

const TILE_VERTEX_OFFSETS: { [key in VertexClass]: [number, number] } = {
    [VertexClass.ABC]: [-TileRef.RADIUS, TileRef.RADIUS/2],
    [VertexClass.ABF]: [0, TileRef.RADIUS],
    [VertexClass.CDE]: [-TileRef.RADIUS, -TileRef.RADIUS/2],
    [VertexClass.DEF]: [0, -TileRef.RADIUS]
}



type EdgeVertexPair = {
    top: VertexRef,
    bottom: VertexRef
}

const EDGE_VERTEX_PAIRS: { [index in EdgeClass]: EdgeVertexPair } = {
    [EdgeClass.A]: {
        top: { vertex_class: VertexClass.ABF, tile: TileRef.THIS },
        bottom: { vertex_class: VertexClass.ABC, tile: TileRef.THIS }
    }, [EdgeClass.B]: {
        top: { vertex_class: VertexClass.ABF, tile: TileRef.THIS },
        bottom: { vertex_class: VertexClass.ABC, tile: TileRef.RIGHT }
    }, [EdgeClass.C]: {
        top: { vertex_class: VertexClass.ABC, tile: TileRef.THIS },
        bottom: { vertex_class: VertexClass.CDE, tile: TileRef.THIS }
    }, [EdgeClass.D]: {
        top: { vertex_class: VertexClass.CDE, tile: TileRef.THIS },
        bottom: { vertex_class: VertexClass.DEF, tile: TileRef.THIS }
    }, [EdgeClass.E]: {
        top: { vertex_class: VertexClass.CDE, tile: TileRef.RIGHT },
        bottom: { vertex_class: VertexClass.DEF, tile: TileRef.THIS }
    }, [EdgeClass.F]: {
        top: { vertex_class: VertexClass.DEF, tile: TileRef.THIS },
        bottom: { vertex_class: VertexClass.ABF, tile: TileRef.DOWN }
    }
}

export const EdgeRef = {
    ends(e: EdgeRef): [EndRef, EndRef] {
        return [
            { ...e, top: true },
            { ...e, top: false }
        ]
    },
    vertex_pair(e: EdgeRef): EdgeVertexPair {
        const edge_vertexes = EDGE_VERTEX_PAIRS[e.edge_class];
        return {
            top: e.tile.offset(edge_vertexes.top),
            bottom: e.tile.offset(edge_vertexes.bottom)
        }
    },
    top_end(er: EdgeRef) {
        return {...er, top: true}
    },
    bottom_end(er: EdgeRef) {
        return {...er, top: false}
    }
}

export const EndRef = {
    other(er: EndRef): EndRef {
        return { ...er, top: !er.top }
    },
    vertex(e: EndRef): VertexRef {
        // endref just says the edge, and whether it's at the top or bottom

        // Get top and bottom vertexes for this edge
        const edge_vertexes = EdgeRef.vertex_pair(e);

        // Return the one we're interested in
        return e.top ? edge_vertexes.top : edge_vertexes.bottom;
    },
    lr(er: EndRef): [EndRef, EndRef] {

        const vertex = EndRef.vertex(er);

        const cw = VertexRef.ends_cw(vertex);

        if (cw[0].edge_class == er.edge_class) {
            return [cw[1], cw[2]];
        } else if (cw[1].edge_class == er.edge_class) {
            return [cw[2], cw[0]];
        } else {
            return [cw[0], cw[1]];
        }
    },

    // Vector pointing from this end to the opposite
    physical_to_next(er: EndRef): [number, number] {
        const from = VertexRef.physical(this.vertex(er));
        const to = VertexRef.physical(this.vertex(this.other(er)));

        return [
            to[0] - from[0],
            to[1] - from[1]
        ]
    }
}


export type HexGridCoord = {
    x: number,
    y: number
}


export const HexGridCoord = {
    // Find the ends of the edges of a hexagon
    *ends(gc: HexGridCoord): Generator<EndRef, void, void> {

        let vertex = gc.y % 2 == 0 ?
            new TileRef(gc.x, Math.floor(gc.y / 2)).vertex(VertexClass.DEF) :
            new TileRef(gc.x+1, Math.floor(gc.y / 2)).vertex(VertexClass.ABC);

        // Get the top end of the vertical below the vertex
        const below = VertexRef.ends_cw(vertex)[0];

        let current = EndRef.lr(below)[1];

        for (let i = 0; i < 6; i++) {
            yield current
            current = EndRef.other(current);
            yield current
            current = EndRef.lr(current)[0]
        }
    }
}

// Can I translate a VertexRef and/or convert to/from a 3-part coord?
// Moving it to the left/right is easy - just add to the tile x
// For the next row down, need to change from a DEF to an ABC vertex
// and subtract 1 from y.

// It's always either an ABC or a DEF hexagon

// Can we go from a vertex to a physical offset
// Easy. The vertex class just has some implicit offset.
// For a given edge, can get a vector from one end to the other.


// Can we map to the 3-part coord system
// Then we can do rotation and translation in those directions


/* 
const v = TileRef.from(1, 0).vertex(VertexClass.CDE);

console.log(v);

const ve = VertexRef.ends_cw(v)
console.log(ve[0]);
const er = ve[0];

console.log(EndRef.other(er))

const lr = EndRef.lr(EndRef.other(er));
console.log(lr);

const other = EdgeRef.vertex_pair(lr[0]);

console.log(other)

console.log([...HexGridCoord.ends({x: 0, y: -1})])

const module_x = er.tile.x / 2;
const module_y = er.tile.y; */
// That decides where the frame is addressed to

// Given an EndRef, we can access the 4 pixels in the appropriate
// module frame.
// Each (tilex%2, edge class) is mapped to some
// location in the 4 neopixel channels.