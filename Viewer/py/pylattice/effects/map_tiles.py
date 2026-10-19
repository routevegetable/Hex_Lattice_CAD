
from pylattice.examples.colors import hsv
from pylattice.examples.tempo import Event
from pylattice.fields.types import Slot
from pylattice.graph import Graph
from pylattice.instrument.types import Effect
from pylattice.lattice_writer import LatticeWriter


class MapTiles(Effect):
    a_hue: Slot
    a_sat: Slot
    a_value: Slot
    
    b_hue: Slot
    b_sat: Slot
    b_value: Slot

    c_hue: Slot
    c_sat: Slot
    c_value: Slot

    def draw_row(self, now: Event, lattice: LatticeWriter, graph: Graph, y: int):

        #print(f"draw: {y}")
        LUT = [
            (self.a_hue, self.a_sat, self.a_value),
            (self.b_hue, self.b_sat, self.b_value),
            (self.c_hue, self.c_sat, self.c_value),
        ]

        # Left to right, alternating through 3
        for x in range(graph.width):

            idx = (x + y) % 3
            fields = LUT[idx % 3]
            filament_idx = x % 3

            hex = graph.HEX[x, y]

            for end in hex.ends():
                h, s, v = [f.get(now, end) for f in fields]
                if v < 0.001:
                    continue

                col = list(hsv(h, s, v))
                lattice[end][filament_idx] = col
                lattice[end.other()][filament_idx] = col



    
    def render(self, now: Event, lattice: LatticeWriter, graph: Graph):

        for y in range((graph.height * 2 - 1)):
            self.draw_row(now, lattice, graph, y)