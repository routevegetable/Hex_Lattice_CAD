import { EdgeClass, EndRef } from "./graph";

// Frame of data for one module
export enum ModuleEdge {
    A1 = 0,
    B1,
    C1,
    D1,
    E1,
    F1,
    A2,
    B2,
    C2,
    D2,
    E2,
    F2,
}


export type RGB = [number, number, number];
export type EndFrame = [RGB, RGB, RGB, RGB]
export type Ends = { top: EndFrame, bottom: EndFrame };
export type EdgeFrame = { ends: Ends; }
export type ModuleFrame = { [index in ModuleEdge]: EdgeFrame }


// Could use the graph to operate directly on the frame.

type EdgeSeq = {
    edge: ModuleEdge,
    points_up: boolean
}
const CHANNEL_EDGES: { [x: number]: EdgeSeq[] } = {
    // Channel 0
    [0]: [
        { edge: ModuleEdge.D1, points_up: true },
        { edge: ModuleEdge.C1, points_up: true },
        { edge: ModuleEdge.A1, points_up: true },
        { edge: ModuleEdge.B1, points_up: false },
        { edge: ModuleEdge.E2, points_up: true },
    ],
    // Channel 1
    [1]: [
        { edge: ModuleEdge.E1, points_up: true },
        { edge: ModuleEdge.C2, points_up: true },
        { edge: ModuleEdge.A2, points_up: true },
        { edge: ModuleEdge.B2, points_up: false },
    ],
    // Channel 2
    [2]: [
        { edge: ModuleEdge.D2, points_up: false },
        { edge: ModuleEdge.F2, points_up: false }
    ],
    // Channel 3
    [3]: [
        { edge: ModuleEdge.F1, points_up: false }
    ]
}

const EDGE_CLASS_TO_MODULE_EDGES: { [index in EdgeClass]: [ModuleEdge, ModuleEdge] } = {
    [EdgeClass.A]: [ModuleEdge.A1, ModuleEdge.A2],
    [EdgeClass.B]: [ModuleEdge.B1, ModuleEdge.B2],
    [EdgeClass.C]: [ModuleEdge.C1, ModuleEdge.C2],
    [EdgeClass.D]: [ModuleEdge.D1, ModuleEdge.D2],
    [EdgeClass.E]: [ModuleEdge.E1, ModuleEdge.E2],
    [EdgeClass.F]: [ModuleEdge.F1, ModuleEdge.F2],
}

const byte = (c: number) => Math.max(0, Math.min(255, Math.round(c * 255)));

export const ModuleFrame = {

    get_end_frame(f: ModuleFrame, er: EndRef): EndFrame {

        const edges = EDGE_CLASS_TO_MODULE_EDGES[er.edge_class];

        const e = f[er.tile.x % 2 == 0 ? edges[0] : edges[1]];

        return er.top ?
            e.ends.top : e.ends.bottom;
    },

    serialize_end_frame(e: EndFrame, arr: Uint8Array, offset: number): number {
        let o = offset;
        for (let i = 0; i < 4; i++) {
            arr[o++] = byte(e[i][0]); // R
            arr[o++] = byte(e[i][1]); // G
            arr[o++] = byte(e[i][2]); // B
        }
        return o;
    },

    serialize(f: ModuleFrame): Uint8Array {

        const EDGES = Object.keys(ModuleEdge).length / 2; // / 2 because values are also keys
        const PIXELS_PER_EDGE = 8;
        const CHANNELS = 4;
        const out = new Uint8Array(CHANNELS + PIXELS_PER_EDGE * EDGES * 3);

        let o = 0;
        for (let iChannel = 0; iChannel < CHANNELS; iChannel++) {
            const edges = CHANNEL_EDGES[iChannel];

            // Channel starts with number of pixels
            out[o++] = edges.length * PIXELS_PER_EDGE;

            for (let iEdge = 0; iEdge < edges.length; iEdge++) {
                const edge_seq = edges[iEdge];
                const edge = f[edge_seq.edge];
                if (edge_seq.points_up) {
                    o = ModuleFrame.serialize_end_frame(edge.ends.bottom, out, o);
                    o = ModuleFrame.serialize_end_frame(edge.ends.top, out, o);
                } else {
                    o = ModuleFrame.serialize_end_frame(edge.ends.top, out, o);
                    o = ModuleFrame.serialize_end_frame(edge.ends.bottom, out, o);
                }
            }
        }
        return out;
    }
}