"""Control-surface inputs read straight out as fields - the same
value at every end, whatever the lattice is doing."""

from pylattice.examples.midi import FloatRange, MIDIFor
from pylattice.examples.tempo import Event
from pylattice.fields.types import ScalarField
from pylattice.graph import EndRef


class CCField(ScalarField):
    """
    A CC as a field
    """

    VALUE = FloatRange(0, 1)

    def __init__(self, midi: MIDIFor, *, value: int):
        self._cc = midi.cc(value, "value", meta=self.VALUE)

    def get(self, now: Event, end: EndRef) -> float:
        return self.VALUE.at(self._cc().data)


class PolyTouchField(ScalarField):
    """
    A polytouch as a field
    """


    def __init__(self, midi: MIDIFor, *, note: int):
        self._poly = midi.polytouch(note)
        
    def get(self, now: Event, end: EndRef) -> float:
        return self._poly() / 127


class FaderField(ScalarField):
    def __init__(self, midi: MIDIFor, fader: int):
        self._fader_cc = midi.cc(fader, "fader")
        self._flipped = False

    def set_flipped(self, flipped: bool):
        self._flipped = flipped

    def get(self, now: Event, end: EndRef) -> float:

        if self._flipped:
            return 1 - self._fader_cc()
        else:
            return self._fader_cc()


class StrobeField(ScalarField):
    """A pad held down, with a limit on how fast the answer may change.

    The pad itself is a square wave - all the way on or all the way off. The
    two knobs are a slew limit on that: the most the output may climb per
    millisecond, and the most it may fall. At 0 each way it is the square wave
    it always was.

    It is a rate rather than a ramp, which is what makes it a limit: let go
    half way up and the fall starts from half way and takes half as long. A
    press part way through a fall climbs from wherever it had got to, rather
    than dropping to nothing first - which matters, because a strobe pressed
    again before it has finished falling is the whole point of a strobe.

    CC:
        * attack - ms to climb the whole way, 0 for instant
        * decay  - ms to fall the whole way, 0 for instant
    """

    ATTACK = FloatRange(0, 2000, "ms")
    DECAY = FloatRange(0, 2000, "ms")

    def __init__(self, midi: MIDIFor, strobe: int, *, attack: int, decay: int):
        self._note = midi.note(strobe, "strobe")
        self._attack_cc = midi.cc(attack, "attack", meta=self.ATTACK)
        self._decay_cc = midi.cc(decay, "decay", meta=self.DECAY)

        # Where it has got to, and the frame that left it there.
        self._value = 0.0
        self._when: int | None = None

    def _advance(self, now: Event):
        """Move towards where the pad says, as fast as the knobs allow. Once a
        frame: every end asks and they all get the same answer."""
        if now.when == self._when:
            return

        pressed = self._note()
        target = 0.0 if pressed is None or pressed[1] is not None else 1.0
        elapsed = 0 if self._when is None else now.when - self._when
        self._when = now.when

        limit = self.ATTACK.at(self._attack_cc().data) if target > self._value \
            else self.DECAY.at(self._decay_cc().data)

        if limit <= 0:
            self._value = target        # no limit asked for, so no limit
            return

        # The whole way takes `limit` ms, so this frame is worth that much of
        # the whole way - and never further than the target.
        step = elapsed / limit

        if target > self._value:
            self._value = min(target, self._value + step)
        else:
            self._value = max(target, self._value - step)

    def get(self, now: Event, end: EndRef) -> float:
        self._advance(now)
        return self._value
