// Hot-reloaded render module for the Hinge Hexagon filament installation.
//
// The viewer re-pulls this file from the server on a short interval; whenever
// its mtime/content changes it is transpiled, re-evaluated, and the exported
// `render` replaces the running one — no page reload needed.
//
// Address scheme (see scheme.md):
//   Frame -> Row[] (by height) -> Module[] (by lateral) ->
//   edge[0..11] -> filament[0..3] -> end[0..1] -> color
//
// A "module" is two segments = 12 tubes (edges). Modules form a grid: one Row
// (ring) per stacked height, and within a row a lateral coordinate 0..N around
// the ring. The viewer maps frame[height][lateral] onto that module; anything
// out of range stays dark. Colour is linear RGB 0..1 (may exceed 1 to bloom).



enum ModuleEdge {
  A = 0,
  B,
  C,
  D,
  E,
  F,
  G,
  H,
  I,
  J,
  K,
  L
}

enum EdgeEnd {
  Top = 0,
  Bottom
}

export type RGB = [number, number, number];
export interface End { color: RGB; }
export type Ends = { [index in EdgeEnd]: End };
export interface Filament { ends: Ends }   // top end, bottom end
export interface Edge { filaments: [Filament, Filament, Filament, Filament]; }
export type Module = { [index in ModuleEdge]: Edge; }          // 12 edges
export type Row = Module[];                          // a ring of modules at one height
export type Frame = Row[];                           // one row per stacked height

enum HexEdge {
    TL = 0,
    TR,
    R,
    BR,
    BL,
    L
}

const CLOCKWISE_HEX_EDGES = [
  HexEdge.TL,
  HexEdge.TR,
  HexEdge.R,
  HexEdge.BR,
  HexEdge.BL,
  HexEdge.L
]


// Physical layout to fill (rows stacked high, modules around each ring).
const ROWS = 2;
const PER_ROW = 32;

type Hex = { [index in HexEdge]: Edge};

const WIDTH = PER_ROW;

type HexCoord = {x: number, y: number};


// Build 2D hex array
// Need to insert hexes into a shared array
// For each module, that contributes to a number of hexagons
// Need to get the offset of a module in the overall array
// A given hex will pull in edges from adjacent modules
// Loop over each module, populating new hex objects in the array.
// for a given module coordinate, need that grid base coordinate

type HexRow = Hex[];
type HexFrame = Row[];


namespace Filament {
  function zero(): Filament {
    return {ends: [
      {color: [0,0,0]},
      {color: [0,0,0]}
    ]}
  }
}



/* A module coordinate, and a module edge */
type ModuleEdgeCoord = {mx: number, my: number, e: ModuleEdge};

/* Hex edge to module offset and module edge */
type HexMapping = {[key in HexEdge]: ModuleEdgeCoord};

/* Here, the module coord is an offset */
const HEX_MAP_SW: HexMapping = {
    [HexEdge.TR]: {mx: 0, my: 0, e: ModuleEdge.A},
    [HexEdge.R]: {mx: 0, my: 0, e: ModuleEdge.B},
    [HexEdge.BR]: {mx: 0, my: 0, e: ModuleEdge.C},
    [HexEdge.BL]: {mx: 0, my: 0, e: ModuleEdge.D},
    [HexEdge.L]: {mx: 0, my: 0, e: ModuleEdge.E},
    [HexEdge.TL]: {mx: 0, my: 0, e: ModuleEdge.F}
}
const HEX_MAP_SE: HexMapping = {
    [HexEdge.TR]: {mx: 0, my: 0, e: ModuleEdge.F},
    [HexEdge.R]: {mx: 0, my: 0, e: ModuleEdge.G},
    [HexEdge.BR]: {mx: 0, my: 0, e: ModuleEdge.H},
    [HexEdge.BL]: {mx: 0, my: 0, e: ModuleEdge.I},
    [HexEdge.L]: {mx: 1, my: 0, e: ModuleEdge.B},
    [HexEdge.TL]: {mx: 0, my: 0, e: ModuleEdge.J}
}
const HEX_MAP_NW: HexMapping = {
    [HexEdge.BL]: {mx: 0, my: 0, e: ModuleEdge.A},
    [HexEdge.BR]: {mx: 0, my: 0, e: ModuleEdge.J},
    /*...*/
}
const HEX_MAP_NE: HexMapping = {
    [HexEdge.BL]: {mx: 0, my: 0, e: ModuleEdge.F},
    /*...*/
}

const HexMapping = {
  for_hex_coord(hc: HexCoord): HexMapping {
    return (hc.y % 2 == 0 ?
      (hc.x % 2 == 0 ? HEX_MAP_SW : HEX_MAP_SE) : 
      (hc.x % 2 == 0 ? HEX_MAP_NW : HEX_MAP_NE));
  }
}

/* Pick a base module location.
 * Each hexagon has a 'base module'.
 * Each module 'owns' 4 hexagons.
 * */

/* 4 cases based on power-of-2-ness: SW, SE, NW, NE */
function map_to_module_edge(hc: HexCoord, e: HexEdge): ModuleEdgeCoord {
  const mx = hc.x / 2;
  const my = hc.y / 2;
  const mapping = HexMapping.for_hex_coord(hc);
  const mapped = mapping[e];
  return {mx: mx + mapped.mx, my: my + mapped.my, e: mapped.e};
}


/* This is enough that we can iterate over all hexes and populate their edges from modules */
/* If we want to iterate over all modules and extract the hexes from them...
 * Duplication is unavoidable anyway. If we have a hex based index, we will have multiple
 * entries for the same edge.
 */


const CLOCKWISE_FIRST_END: {[index in HexEdge]: EdgeEnd} = {
  [HexEdge.TL]: EdgeEnd.Top,
  [HexEdge.L]: EdgeEnd.Top,
  [HexEdge.BL]: EdgeEnd.Top,
  [HexEdge.TR]: EdgeEnd.Bottom,
  [HexEdge.R]: EdgeEnd.Bottom,
  [HexEdge.BR]: EdgeEnd.Bottom
}

function other_end(end: EdgeEnd): EdgeEnd {
  return end == EdgeEnd.Bottom ? EdgeEnd.Top : EdgeEnd.Bottom;
}

function *clockwise(he: HexEdge, f: Filament): Generator<End, void, void> {
  const first_end = CLOCKWISE_FIRST_END[he];
  yield f.ends[first_end];
  yield f.ends[other_end(first_end)];
}

function *clockwise_edges(hex: Hex): Generator<Edge, void, void> {
  while(true) {
    yield* CLOCKWISE_HEX_EDGES.map(he => hex[he])
  }
}


// Angle points from bottommost to topmost
const MODULE_EDGE_ANGLE: {[key in ModuleEdge]: number} = {
  [ModuleEdge.A]: ...
}

// Angle points clockwise
function clockwise_hex_edge_angle(hc: HexCoord, e: HexEdge): number {
  const mec = map_to_module_edge(hc, e);

  const from_end = CLOCKWISE_FIRST_END[e];

  const module_angle = MODULE_EDGE_ANGLE[mec.e];
  if(from_end == EdgeEnd.Bottom) {
    // Same as module edge angle
    return module_angle;
  } else {
    return (module_angle + 180) % 360;
  }
}

/**
 * If we have a hexagon, and a hexedge within that, it has two ends - a top and a bottom one.
 * There are two orientations for a hexedge -
 * the topmost is the clockwise end,
 * and the bottomost end is the clockwise end.
 * 
 * topwise and bottomwise, respectively, are cute and confusing names for this.
 * 
 */

namespace Edge {
  function zero(): Edge {
    function 
  }
}

namespace Edge {
  function Blank
}

namespace HexRow {
  function blank(): HexRow {
    return {

    }
  }
}

const HEX_FRAME: HexRow = [];
function map_frame(modules: Frame): HexFrame {

  const hex_frame: HexFrame = [];

  /* Generate hexes */
  for(const my of modules.keys()) {
    /* Row */
    const hex_row: HexRow = [];
    for(const mx of modules[0].keys()) {
      hex_row.push(Object.keys(Hex).);
    }
  }


  for(const [my, row] of modules.entries()) {


    for(const [mx, module] of row.entries()) {

    }
  }

  return hex_frame;
}



// --- helpers ---------------------------------------------------------------
function hsv(h: number, s: number, v: number): RGB {
  h = ((h % 1) + 1) % 1;
  const i = Math.floor(h * 6), f = h * 6 - i;
  const p = v * (1 - s), q = v * (1 - f * s), u = v * (1 - (1 - f) * s);
  switch (i % 6) {
    case 0: return [v, u, p]; case 1: return [q, v, p]; case 2: return [p, v, u];
    case 3: return [p, q, v]; case 4: return [u, p, v]; default: return [v, p, q];
  }
}

// Build one module (12 edges x 4 filaments x 2 ends) from a colour callback.
function module(color: (edge: number, fil: number, end: number) => RGB): Module {
  const edges: Edge[] = [];
  for (let e = 0; e < 12; e++) {
    const filaments = [] as unknown as Edge["filaments"];
    for (let f = 0; f < 4; f++)
      filaments.push({ ends: [{ color: color(e, f, 0) }, { color: color(e, f, 1) }] });
    edges.push({ filaments });
  }
  return { edges };
}

// One ring of modules at a given height.
function get_ring(t: number, height: number): Row {
  const row: Row = [];
  for (let lateral = 0; lateral < PER_ROW; lateral++) {
    row.push(module((edge, fil, end) => {
      const hue = lateral / PER_ROW + height * 0.35 + edge * 0.01 + t * 0.05;
      const v = 0.5 + 0.5 * Math.sin(t * 2 - lateral * 0.3 - edge * 0.2 + height * 1.5 - end * 0.9);
      return hsv(hue + end * 0.1, 1, v);
    }));
  }
  return row;
}

// --- the render function ---------------------------------------------------
// Called every frame with the current time in seconds; returns the whole frame
// as rows of modules. Edit freely and save — the change appears live.
export function render(t: number): Frame {
  const frame: Frame = [];
  for (let height = 0; height < ROWS; height++) frame.push(get_ring(t, height));
  return frame;
}
