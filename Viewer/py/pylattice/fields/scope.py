"""A spot going round and round one line of the lattice."""
import itertools

from pylattice.examples.midi import MIDIFor
from pylattice.examples.tempo import Event, ZERO, psweep
from pylattice.fields.types import ScalarField
from pylattice.graph import EdgeClass, EndRef, Graph, TileRef


class ScopeFieldBetter(ScalarField):


    PATTERNS = [
        (0, EdgeClass.A, "RL"),   # Tile Y coord, edge class, path
        (0, EdgeClass.A, "LRRRLL"),
        (0, EdgeClass.A, "LRLRRRLRLL"),
        (0, EdgeClass.A, "LRLRRLRRLRLRLLLR"),
        (0, EdgeClass.E, "LRRLRLRLRLRL"),
    ]
    def __init__(self, graph: Graph, midi: MIDIFor, *, speed: int, pattern: int):
        self._width = graph.width * TileRef.WIDTH
        self._height = graph.height * TileRef.HEIGHT
        self._graph = graph

        self._speed_cc = midi.cc(speed, "speed")
        self._pattern_cc = midi.cc(pattern, "pattern")

        self._phases: dict[EndRef, list[float]] = {} # 0 to 1
        self._built_time = ZERO

    
    def _rebuild_phases(self, now: Event):

        if self._built_time == now:
            return
        self._phases = {}

        pattern_idx = min(self._pattern_cc().data, len(self.PATTERNS)-1)

        start_tile_y, edge_class, path = self.PATTERNS[pattern_idx]

        start = self._graph.TILE[0, start_tile_y].bottom_end(edge_class)

        # Construct the list of vertexes in this path, overall going left to right
        path_ends: list[EndRef] = []
        last_end = None
        for end in start.path(itertools.cycle(path)):

            if len(path_ends) > 0 and path_ends[0] == end:
                break

            # Add to the vertex list
            path_ends.append(end)

            if last_end is not None:
                path_ends.append(end.other())

            last_end = end
            
        
        # Generate the phases
        for i, v in enumerate(path_ends):

            phase = i / len(path_ends)
            if v not in self._phases:
                self._phases[v] = []
            self._phases[v].append(phase)
            #if v not in self._phases or self._phases[v] < phase:
            #    self._phases[v] = phase 

            #print(f"phases{v} = {phase}")
        #print(self._phases)

        self._built_time = now

    def get(self, now: Event, end: EndRef) -> float:

        # 4 sec at 0 down to 30ms at 127, a constant ratio per step
        period = 4000 * (30 / 4000) ** (self._speed_cc().data / 127)

        self._rebuild_phases(now)

        if end in self._phases:
            #return 1 # TODO Thing

            phases = self._phases[end]
            result = 0
            for phase in phases:
                result = max(result,psweep(now.delay(period * -phase), period, 1, 0))
            return result
            
        else:
            return 0
