"""A random number per edge, re-rolled on a note."""

from pylattice.examples.midi import MIDIFor
from pylattice.examples.tempo import Event, ZERO, sweep
from pylattice.fields.types import ScalarField
from pylattice.graph import EndRef


class NoteRandomField(ScalarField):
    """
    A note that re-rolls every edge to a new random number.

    One value per edge, so both of its ends read the same - they are two ends
    of the same thing. A press glides every edge from where it was to a fresh
    number, all of them together, over however long the knob says.

    What an edge lands on comes out of the press event itself, so nothing is
    stored but the two presses being crossfaded between. Both start seeded at
    time zero, which gives a still pattern to begin with rather than nothing.

    CC:
        * period - how long the glide takes, 4s at 0 down to 30ms at 127
    """

    def __init__(self, midi: MIDIFor, *, note: int, period: int):
        self._note = midi.note(note)
        self._period_cc = midi.cc(period, "period")

        # The press being faded from and the one being faded to.
        self._from: Event = ZERO
        self._to: Event = ZERO
        self._seen: Event | None = None

    def _consume_note(self):
        """Start a fresh glide on a new press. A release ends nothing."""
        pressed = self._note()
        if pressed is None:
            return

        on, _release = pressed
        if not on.after(self._seen):
            return              # already rolling on this press

        self._seen = on
        self._from = self._to
        self._to = on

    def _value(self, ev: Event, edge: EndRef) -> float:
        """What an edge settles on for a given press."""
        return ev.rand(hash(edge)) % 1000 / 1000

    def get(self, now: Event, end: EndRef) -> float:
        self._consume_note()

        # Both ends of an edge answer with the edge's own number.
        edge = end if end.top else end.other()

        # 4s at 0 down to 30ms at 127, a constant ratio per step - a
        # reciprocal spends all its useful travel in the first sixth.
        period = 4000 * (30 / 4000) ** (self._period_cc().data / 127)
        return sweep(now, self._to, period,
                     self._value(self._from, edge), self._value(self._to, edge))
