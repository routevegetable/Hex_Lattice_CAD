from pylattice.examples.colors import hsv, vary
from pylattice.examples.tempo import Event
from pylattice.fields.types import Slot
from pylattice.graph import EdgeClass, EndRef, Graph
from pylattice.instrument.types import Effect
from pylattice.lattice_writer import LatticeWriter


class BisexualSpin(Effect):
    value: Slot
    speed: Slot


    def draw_hex(self, now: Event, base: EndRef, lattice: LatticeWriter):
        val = self.value.get(now, base)
        if val < 0.001:
            return
        hue = 0.8

        period = self.speed.get(now, base) * 10000 + 1

        if period > 500:
            period = 10000
        else:
            period = 500

        for dist, end in enumerate(base.path("RRRRR")):

            f = dist / 6

            #hue = vary(now, 0.66, 1, 5000, f)

            for i in range(4):

                hue = vary(now, 0.66, 1.02, period, f + i*0.05)
                #print(hue)
                col = list(hsv(hue, 1, val))
                lattice[end][i] = col
                lattice[end.lr()[0]][i] = col




    def render(self, now: Event, lattice: LatticeWriter, graph: Graph):


        for base in [
            graph.TILE[0,0].bottom_end(EdgeClass.D),
            graph.TILE[1,0].bottom_end(EdgeClass.B),
            graph.TILE[3,1].bottom_end(EdgeClass.D),
            graph.TILE[4,0].bottom_end(EdgeClass.B),
        ]:
            self.draw_hex(now, base, lattice)

        return
