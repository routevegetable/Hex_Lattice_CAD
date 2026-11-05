"""One sinusoid, the same at every end, going round at whatever rate the knob says."""
import copy
import math
from typing import Callable

from pylattice.examples.midi import FloatRange, MIDIFor
from pylattice.examples.tempo import Event
from pylattice.fields.types import ScalarField
from pylattice.graph import EndRef

TAU = 2 * math.pi


class Cycle:
    """How far one cycle has got, and how fast it is going.

    Held apart from the field for the same reason rotary's Rotation is: more
    than one field reads it, and copies a fixed distance apart have to share a
    phase rather than keep one each. Separate accumulators only stay in step
    while both are being asked, and a field in no slot is not asked at all - so
    they would drift the moment one of them was unpatched, and the four would
    no longer be a third of a cycle apart.
    """

    # A rate knob, so up is faster and the period shrinks as it rises.
    # Geometric, so each step is the same proportion rather than the slow end
    # being crowded into the first few.
    RATE = FloatRange(1000, 100, "ms", geometric=True)

    def __init__(self, rate: Callable[[], Event[int]]):
        self._rate = rate
        self.phase = 0.0
        self._when: int | None = None

    def advance(self, now: Event):
        """Move the phase on by however long it has been. Once a frame: every
        end asks, and they all want the same answer."""
        if now.when == self._when:
            return

        if self._when is not None:
            period = self.RATE.at(self._rate().data)
            self.phase = (self.phase + (now.when - self._when) / period) % 1.0

        self._when = now.when


class LFOField(ScalarField):
    """A sine between 0 and 1, every end alike, cycling at a set rate.

    Position does not come into it: this is a value over time and nothing else
    - what rotary would be if the wave had no length. On its own it breathes
    the whole lattice at once; multiplied with a field that does have a shape,
    it makes that shape come and go.

    The phase accumulates rather than being worked out from the clock. Reading
    the clock - "how far into the current period are we" - leaves the answer at
    the mercy of where the period boundaries fall, so turning the knob moves
    those boundaries and the wave jumps to wherever the new grid says it should
    be. Adding on however long the frame took instead, the knob changes only
    the rate: the wave is wherever it got to and carries on from there.

    The cost is that it only moves while something is reading it. With no copy
    of it in any slot it stands still rather than turning over unseen, and
    picks up where it left off when one is patched back in.

    CC:
        * rate - 1s a cycle at 0, down to 100ms at 127
    """

    RATE = Cycle.RATE

    def __init__(self, midi: MIDIFor, *, rate: int):
        self._cycle = Cycle(midi.cc(rate, "rate", meta=Cycle.RATE))

        # How far round from the cycle itself this copy sits, 0-1.
        self._turn = 0.0

    def turned(self, turn: float) -> "LFOField":
        """This same cycle, read a fraction of a turn further round.

        A copy rather than an LFO of its own, so it shares the one phase and
        stays exactly `turn` away however long either of them goes unread. It
        shares the knob too - it is the same cycle, seen from elsewhere.
        """
        sibling = copy.copy(self)
        sibling._turn = turn
        return sibling

    def get(self, now: Event, end: EndRef) -> float:
        self._cycle.advance(now)
        return math.sin(TAU * (self._cycle.phase + self._turn)) / 2 + 0.5
