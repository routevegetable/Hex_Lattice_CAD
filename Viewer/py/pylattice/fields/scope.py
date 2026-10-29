"""A spot going round and round one line of the lattice."""
import itertools

from pylattice.examples.midi import CustomChoice, FloatRange, MIDIFor
from pylattice.examples.tempo import Event, ZERO, trail
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
    # 4 sec at 0 down to 30ms at 127.
    SPEED = FloatRange(4000, 30, "ms", geometric=True)

    # How long the head takes to come up to full as it arrives. 0 is a hard
    # edge, which is how it was before there was a knob for it.
    ATTACK = FloatRange(0, 1000, "ms")

    def __init__(self, graph: Graph, midi: MIDIFor, *, speed: int, pattern: int,
                 attack: int, phase_offset: float = 0):
        self._width = graph.width * TileRef.WIDTH
        self._height = graph.height * TileRef.HEIGHT
        self._graph = graph

        self._speed_cc = midi.cc(speed, "speed", meta=self.SPEED)
        self._attack_cc = midi.cc(attack, "attack", meta=self.ATTACK)
        # Not a sweep: the value indexes PATTERNS directly, so the UI is
        # better off listing them than offering 0-127 of which only five mean
        # anything.
        self._pattern_cc = midi.cc(
            pattern, "pattern",
            meta=CustomChoice({index: path
                               for index, (_, _, path) in enumerate(self.PATTERNS)}))
        self._phase_offset = phase_offset

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

        self._built_time = now

    def get(self, now: Event, end: EndRef) -> float:

        period = self.SPEED.at(self._speed_cc().data)
        attack = self.ATTACK.at(self._attack_cc().data)

        self._rebuild_phases(now)

        if end in self._phases:
            phases = self._phases[end]
            result = 0
            for phase in phases:
                result = max(result,
                             trail(now, period, phase + self._phase_offset, attack))
            return result
            
        else:
            return 0
