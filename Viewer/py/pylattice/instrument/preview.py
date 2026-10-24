"""What a formula would do, on a rig of its own.

The visual cheatsheet asks to see a formula played out: a value per end, moving.
It cannot be played on the rig itself - fields hold what they last heard, and a
preview pressing a pad would ripple through whatever is playing. So a Preview
makes its own set of fields against a MIDI with nothing plugged in, and plays
them from there.

Knobs and faders have no press to simulate, so they sit at halfway. Pads are
pressed for a second and let go for a second, over and over, starting pressed.
"""

import math
import time

from pylattice.examples.midi import MIDI
from pylattice.examples.tempo import Event
from pylattice.fields.types import ScalarField
from pylattice.frame import EDGE_CLASS_TO_MODULE_EDGES
from pylattice.graph import Graph
from pylattice.instrument.console import field_group
from pylattice.instrument.fields import build_fields
from pylattice.instrument.patch import as_ref, decode_field, named

HALFWAY = 127 / 2  # a knob at 0.5, as the 0-127 a CC reads
PRESSED = 1.0  # seconds a pad is held
RELEASED = 1.0  # and let go
VELOCITY = 127


def field_names(tree) -> set[str]:
    """The fields a formula names, however deep."""
    if isinstance(tree, str):
        return {tree}
    if isinstance(tree, dict):
        return field_names(tree.get("a")) | field_names(tree.get("b"))
    return set()


class Preview:
    """One formula, played against fields nobody else is touching.

    Raises ValueError for a formula the rig would refuse.
    """

    def __init__(self, tree, graph: Graph, artnet):
        self._midi = MIDI(None)
        fields = named(build_fields(graph, self._midi, artnet), ScalarField)

        self._field = decode_field(as_ref(tree), fields)

        # Every knob the fields listen to, held at halfway.
        for number in self._midi.get_ccs_by_number():
            self._midi.set_cc(number, HALFWAY)

        self.uses_pad = any(
            field_group(name, fields[name]) == "pads"
            for name in field_names(tree)
            if name in fields
        )

        # Where each end lands in a frame. The viewer draws modules of two
        # tiles side by side (x), stacked in rows (y); a module has twelve
        # edges, the first six from its even tile and the rest from its odd one,
        # each with a top end and then a bottom.
        self._ends = []
        for end in graph.ends():
            module = (end.tile.x // 2) * graph.height + end.tile.y
            edge = EDGE_CLASS_TO_MODULE_EDGES[end.edge_class][end.tile.x % 2]
            self._ends.append(
                (((module * 12) + int(edge)) * 2 + (0 if end.top else 1), end)
            )

        self.size = max(i for i, _ in self._ends) + 1
        self._started = time.monotonic()
        self._pressed = False

    def _hold(self, pressed: bool):
        """Press every pad, or let them all go - as the desk would send it."""
        for note in self._midi.get_notes().values():
            if pressed:
                note.off.clear()  # this press is not over
                note.on.put(VELOCITY)
                note.pressure = VELOCITY
            else:
                note.off.put(0)

    @property
    def pressed(self) -> bool:
        """Whether the pads are down, by the clock."""
        elapsed = (time.monotonic() - self._started) % (PRESSED + RELEASED)
        return elapsed < PRESSED

    def frame(self) -> bytes:
        """The pad's state as one byte, then a byte per end, 0-255 for 0-1."""
        pressed = self.pressed
        if self.uses_pad and pressed != self._pressed:
            self._hold(pressed)
        self._pressed = pressed

        now = Event.for_now()
        out = bytearray(1 + self.size)
        out[0] = int(pressed and self.uses_pad)

        for at, end in self._ends:
            value = self._field.get(now, end)
            if not math.isfinite(value):
                value = 0.0
            out[1 + at] = round(max(0.0, min(1.0, value)) * 255)

        return bytes(out)
