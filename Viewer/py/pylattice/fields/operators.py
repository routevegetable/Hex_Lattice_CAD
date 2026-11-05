from enum import StrEnum, auto

from pylattice.examples.midi import (
    CCMeta,
    CustomChoice,
    FloatRange,
    GradientChoice,
    MIDIFor,
)
from pylattice.examples.tempo import ZERO, Event, EventLatch, periodic, sweep
from pylattice.fields.gradients import GradientLibrary
from pylattice.fields.types import ScalarField
from pylattice.graph import EndRef, Graph


class Arity(StrEnum):
    """How many arguments an operator is written with.

    For showing one, not for checking one: nothing enforces it, and `get` is
    handed however many the expression names. It is here so a UI can lay the
    operands out and say what an operator wants, rather than inferring it from
    however many a saved expression happens to have.
    """

    UNARY = auto()
    BINARY = auto()
    NARY = auto()


class Operator:
    """
    Long-lived thingy
    """

    # Presentation only - see Arity. `nary` is what an operator that has not
    # said is, rather than a guess at what it meant: `get` takes however many
    # it is given, so that is the truthful answer until one says otherwise.
    #
    # Usually set on the class, since what an operator is written with is a
    # property of the operator. An operator built round something else - Math,
    # round a callable - sets it per instance instead, because that is where
    # the number lives, so it is read off the object rather than its class.
    arity: Arity = Arity.NARY

    def get(self, now: Event, end: EndRef, *args: ScalarField) -> float: ...






class ProbZap(Operator):
    """A zap per end, at the likelihood its argument reads there.

    Every end rolls its own chance a few times a second, and when one comes up
    it sweeps from 1 down to 0 over the length on the knob. Dark the rest of
    the time - before anything has fired and once a sweep has run out - so
    what comes out is mostly nothing with the odd flash, as often as the field
    asks for.

    The same pieces the ProbZaps effect fires its edges with, read as a value
    instead of drawn: a latch per end, rolled with `maybe`, swept with
    `sweep`. Unary for the same reason the effect keeps its length on a knob
    rather than in a slot - the argument says how often, and how long a flash
    lasts shapes it rather than driving it.

    One object per operator, so two slots both naming this share its latches
    and flash together. That is what makes a zap's hue and its brightness the
    same zap, the way the effect's saturation and value envelopes are.
    """

    arity = Arity.UNARY

    SHORTEST = 60       # ms a zap takes to fade at CC 0, as the effect has it
    LONGEST = 1500      # ms at CC 127
    LENGTH = FloatRange(SHORTEST, LONGEST, "ms", geometric=True)

    # How often an end rolls its chance, in ms, jittered per end rather than
    # one rate for all of them. On a single period every end rolls on the same
    # tick, and one likelihood across the lattice would flash the whole thing
    # at once instead of scattering.
    SOONEST = 10
    SPREAD = 30

    def __init__(self, graph: Graph, midi: MIDIFor, length: int):
        self._length = midi.cc(length, "length", meta=self.LENGTH)

        # end -> its latch, how often it rolls, and what it salts the roll
        # with. Built from the graph up front, and the period and salt worked
        # out once: both come off the end, and a get happens per end per frame.
        self._ends = {
            end: (EventLatch(), self.SOONEST + end.__hash__() % self.SPREAD,
                  end.__hash__())
            for end in graph.ends()
        }

    def get(self, now: Event, end: EndRef, *args: ScalarField) -> float:
        latch, period, salt = self._ends[end]
        trigger = latch.maybe(now, salt, period, args[0].get(now, end))

        # 1 the moment it fires, 0 by the end of the length, and 0 while
        # nothing has - the shape of the effect's own value envelope.
        return sweep(now, trigger, self.LENGTH.at(self._length().data), 1, 0, 0)


class Cycle(Operator):
    """One argument after another, on the clock instead of on a knob.

    Select with the picking automated: each argument has its turn for as long
    as the rate says, and the turn after the last argument's is the first
    argument's again. Only the one showing is evaluated, so the others cost
    nothing while they wait.

    The knob sets how long a *step* lasts, not how long a lap does. A fifth
    argument then simply appends, where a lap-length knob would have to speed
    the other four up to keep the lap the same - and the rate on the desk
    would stop meaning what it meant.
    """

    arity = Arity.NARY

    # A rate, so the period it names runs the other way: slow at the bottom of
    # the knob, fast at the top, as LFOField's does.
    RATE = FloatRange(2000, 60, "ms", geometric=True)

    def __init__(self, midi: MIDIFor, rate: int):
        self._rate = midi.cc(rate, "rate", meta=self.RATE)

    def get(self, now: Event, end: EndRef, *args: ScalarField) -> float:
        # Whose turn it is comes off the clock, not off any state of its own:
        # every end is on the same argument at the same moment, and nothing
        # drifts if a frame is missed.
        step = periodic(now, int(self.RATE.at(self._rate().data)))

        return args[step.data % len(args)].get(now, end)


class Randomize(Operator):
    """One argument at random, re-picked whenever a pad is hit.

    Select with the choosing handed to a pad: a press picks afresh and that
    one holds until the next press. Only the chosen argument is evaluated, so
    the rest cost nothing while they are not up.

    Which one comes out of the press event itself, the way NoteRandomField's
    numbers do, so there is nothing to store: the same press always picks the
    same argument, and every end agrees on it without being told. Seeded at
    time zero, so before anything is played it is sitting on one argument
    rather than on none.
    """

    arity = Arity.NARY

    def __init__(self, midi: MIDIFor, note: int):
        self._note = midi.note(note)

    def get(self, now: Event, end: EndRef, *args: ScalarField) -> float:
        pressed = self._note()
        press = ZERO if pressed is None else pressed[0]

        # A release picks nothing: the choice is made on the way down and held.
        return args[press.rand() % len(args)].get(now, end)


class Select(Operator):
    """
    Long lived thing that can also be called with arguments.
    Passing fields to fields is now possible :O
    """

    # One of however many it is offered, so there is no number to state.
    arity = Arity.NARY

    def __init__(self, midi: MIDIFor, select: int):
        self._select_cc = midi.cc(select, "select", CustomChoice({i:str(i) for i in range(10)}))

    def get(self, now: Event, end: EndRef, *args: ScalarField) -> float:
        # Stuff to look up a given gradient in the currently selected patch

        sel = self._select_cc().data
        try:
            f = args[sel]
            assert isinstance(f, ScalarField)
            return f.get(now, end)
        except:
            # Probably missing the requested arg
            return 0
        
class GradientChooser(Operator):
    """The hue or the saturation of a gradient, at wherever its argument says.

    A knob picks which gradient, by position (see `fields/gradients.py`), and
    the argument says where along it to be: `gradient_1_h(wipe1)` is the hue
    of whatever gradient knob 1 is on, at the place wipe1 reads. Hue and
    saturation are separate operators so a slot can take either alone, or
    mix one with something else; the two that share a knob are named after it
    (`gradient_1_h`, `gradient_1_s`), which is why they share an owner on the
    desk - see docs/CONTROLS.md.

    Reads the gradient out of the library on every call, so a preset's own
    gradients are the ones heard once it is playing. With no gradient at all
    to land on it reads 0, which is dark, not a crash.
    """

    # The one field it reads the gradient at.
    arity = Arity.UNARY

    def __init__(
        self,
        hue: bool,
        midi: MIDIFor,
        select: int,
        library: GradientLibrary,
    ):
        self._hue = hue
        self._library = library
        self._select_cc = midi.cc(select, "select", GradientChoice())

    def get(self, now: Event, end: EndRef, *args: ScalarField) -> float:
        gradient = self._library.at(self._select_cc().data)

        if gradient is None:
            return 0.0

        hue, sat = gradient.at(args[0].get(now, end))

        return hue if self._hue else sat


class OperatorField(ScalarField):
    """One node of an expression: an operator, and the fields it reads.

    The operator is long-lived and shared between every node that names it;
    this is what holds the arguments. They go in unevaluated, so an operator
    that only wants some of them - Select reads the one it picked - does not
    pay for the rest.
    """

    def __init__(self, op: Operator, mod: bool, *args: ScalarField):
        self._op = op
        self._mod = mod
        self._args = args

    def get(self, now: Event, end: EndRef) -> float:
        value = self._op.get(now, end, *self._args)

        if self._mod:
            return value % 1

        return min(max(value, 0), 1)

    def __repr__(self) -> str:
        return (f"{type(self._op).__name__}"
                f"({', '.join(repr(arg) for arg in self._args)})")
