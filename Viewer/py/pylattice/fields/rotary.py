"""A value sweeping round the lattice, left to right or up to down, forever."""

import copy
import math
from typing import Callable

from pylattice.examples.midi import MIDIFor
from pylattice.examples.tempo import Event
from pylattice.fields.types import ScalarField
from pylattice.graph import EndRef, Graph, TileRef

TAU = 2 * math.pi


class Rotation:
    """How far one turn of the lattice has got, and how fast it is going.

    Held apart from the field because more than one field reads it: two copies
    a fixed distance apart have to share a phase, not keep one each. Separate
    accumulators only stay in step while both are being asked, and a field in
    no slot is not asked at all - so they would drift the moment one of them
    was unpatched, and the pair would no longer be half a turn apart.
    """

    def __init__(self, period: Callable[[], Event[int]]):
        self._period = period
        self.phase = 0.0
        self._when: int | None = None

    def advance(self, now: Event):
        """Move the phase on by however long it has been. Once a frame: every
        end asks, and they all want the same answer."""
        if now.when == self._when:
            return

        # 0.5s a rotation at 0 up to 16s at 127, a constant ratio per step.
        # Doubling per CC step ran off the end of the knob by about step 5.
        period = 500 * (16000 / 500) ** (self._period().data / 127)

        if self._when is not None:
            self.phase = (self.phase + (now.when - self._when) / period) % 1.0

        self._when = now.when


class RotaryField(ScalarField):
    """A sine wave wrapped once round the lattice, either vertically
    or horizontally, rotating at a certain period.

    The phase is accumulated rather than worked out from the clock: each frame
    it moves on by however long that frame took, divided by the period the knob
    is asking for. Reading the clock instead - "how far into the current period
    are we" - means the answer depends on where the period boundaries happen to
    fall, so turning the period knob moves those boundaries and the wave jumps
    to wherever the new grid says it should be. Accumulating, the knob changes
    only the rate: the wave is wherever it got to and carries on from there.

    The cost is that the phase only moves while something is reading the field.
    A field in no slot stands still rather than turning on unseen, and picks up
    where it left off when it is patched in again.

    CC:
        * period - 0.5s a rotation up to 16s
        * parts  - unused
        * shape  - unused

    vert keyword: whether to loop up-to-down instead of left-to-right
    """

    def __init__(
        self,
        graph: Graph,
        midi: MIDIFor,
        *,
        period: int,
        parts: int,
        shape: int,
        vert: bool = False
    ):
        self._width = graph.width
        self._height = graph.height
        self._rotation = Rotation(midi.cc(period, "period"))
        self._parts = midi.cc(parts, "parts")
        self._shape = midi.cc(shape, "shape")

        # How far round from the rotation itself this copy sits, 0-1.
        self._turn = 0.0

        self._vert = vert

    def turned(self, turn: float) -> "RotaryField":
        """This same rotation, read a fraction of a turn further round.

        A copy rather than a field of its own, so it shares the one phase and
        stays exactly `turn` away however long either of them goes unread. It
        shares the knobs too - it is the same rotation, seen from elsewhere.
        """
        sibling = copy.copy(self)
        sibling._turn = turn
        return sibling

    def get(self, now: Event, end: EndRef) -> float:
        self._rotation.advance(now)

        # Where this end sits across the lattice, 0-1, which is its place in
        # the wave: one whole turn spans the width (or height, for vertical rotation)
        if not self._vert:
            offset = end.vertex().physical()[0] / (TileRef.WIDTH * self._width)
        else:
            offset = end.vertex().physical()[1] / (TileRef.HEIGHT * self._height)

        return math.sin(TAU * (self._rotation.phase + self._turn + offset)) / 2 + 0.5
