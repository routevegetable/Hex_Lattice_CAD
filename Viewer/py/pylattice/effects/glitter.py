import math

from pylattice.examples.colors import hsv
from pylattice.examples.tempo import ZERO, Event
from pylattice.fields.types import ScalarField, Slot
from pylattice.graph import EdgeRef, Graph
from pylattice.instrument.types import Effect
from pylattice.lattice_writer import LatticeWriter


def glitter(
    now: Event,
    lattice: LatticeWriter,
    graph: Graph,
    hue_1: ScalarField,
    hue_2: ScalarField,
    value: ScalarField,
    spin_rate: ScalarField,  # max 10 radians / second
    phases: dict[EdgeRef, float],
    last_frame_time: Event,
):
    # milliseconds
    dt = now.when - last_frame_time.when
    for edge in graph.edges():
        top, bottom = edge.ends()
        if edge not in phases.keys():
            phases[edge] = 0

        edge_rate = (spin_rate.get(now, top) + spin_rate.get(now, bottom)) / 2
        phase = (phases[edge] + (edge_rate * dt / 20)) % (2.0 * math.pi)
        phases[edge] = phase

        actual_hue_1 = (hue_1.get(now, top) + hue_1.get(now, bottom)) / 2
        actual_hue_2 = (hue_2.get(now, top) + hue_2.get(now, bottom)) / 2

        actual_value = (value.get(now, top) + value.get(now, top)) / 2

        π = math.pi

        if phase > π / 2 and phase < 3 * π / 2:
            top_hue = actual_hue_1
            bottom_hue = actual_hue_2
        else:
            top_hue = actual_hue_2
            bottom_hue = actual_hue_1

        # sat = min((math.sin(phase) / 4) + 0.85, 1)
        sat = 1

        lattice[top][0] = list(hsv(top_hue, sat, actual_value))
        lattice[bottom][0] = list(hsv(bottom_hue, sat, actual_value))


class Glitter(Effect):
    hue_1: Slot
    hue_2: Slot
    value: Slot
    spin_rate: Slot

    phases: dict[EdgeRef, float] = {}

    last_frame_time: Event = ZERO

    def render(self, now: Event, lattice: LatticeWriter, graph: Graph):
        glitter(
            now,
            lattice,
            graph,
            self.hue_1,
            self.hue_2,
            self.value,
            self.spin_rate,
            self.phases,
            self.last_frame_time,
        )
        self.last_frame_time = now
