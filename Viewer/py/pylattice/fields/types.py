"""What a field is: the protocols it implements, and how fields combine."""

import operator
import traceback
from dataclasses import dataclass
from time import perf_counter_ns
from typing import Protocol, runtime_checkable

from pylattice.examples.tempo import Event
from pylattice.frame import RGB
from pylattice.graph import EndRef


@runtime_checkable
class ScalarField(Protocol):
    """
    Something that has a value for each end.

    Runtime-checkable, so `isinstance(x, ScalarField)` works - which is how a
    group of fields declared in a class body gets enumerated.
    Rotating.
    Wiping.
    Particle distance.
    """

    def get(self, now: Event, end: EndRef) -> float: ...

    # Combining fields. The other side may be a field or a plain number, and
    # the reflected forms let the number come first - `1 - wipe`.
    def __add__(self, other: "ScalarField | float") -> "ScalarField":
        return _combine(operator.add, self, other)

    def __radd__(self, other: "ScalarField | float") -> "ScalarField":
        return _combine(operator.add, other, self)

    def __sub__(self, other: "ScalarField | float") -> "ScalarField":
        return _combine(operator.sub, self, other)

    def __rsub__(self, other: "ScalarField | float") -> "ScalarField":
        return _combine(operator.sub, other, self)

    def __mul__(self, other: "ScalarField | float") -> "ScalarField":
        return _combine(operator.mul, self, other)

    def __rmul__(self, other: "ScalarField | float") -> "ScalarField":
        return _combine(operator.mul, other, self)

    def __truediv__(self, other: "ScalarField | float") -> "ScalarField":
        return _combine(divide, self, other)

    def __rtruediv__(self, other: "ScalarField | float") -> "ScalarField":
        return _combine(divide, other, self)


class ColorField(Protocol):
    """
    Something that has a color for each end.
    """

    def get(self, now: Event, end: EndRef) -> RGB: ...


class ConstantField(ScalarField):
    """The same value at every end - what a number becomes in a combination."""

    def __init__(self, value: float):
        self._value = float(value)

    @property
    def value(self) -> float:
        return self._value

    def get(self, now: Event, end: EndRef) -> float:
        return self._value

    def __repr__(self) -> str:
        return f"ConstantField({self._value})"


class CombinedField(ScalarField):
    """Two fields under an operator, evaluated at the same end."""

    def __init__(self, op, a: ScalarField, b: ScalarField, mod: bool):
        self._op = op
        self._a = a
        self._b = b
        self._mod = mod

    def get(self, now: Event, end: EndRef) -> float:
        res = self._op(self._a.get(now, end), self._b.get(now, end))
        if self._mod:
            return res % 1
        return min(max(res, 0), 1)

    def __repr__(self) -> str:
        return f"({self._a!r} {self._op.__name__} {self._b!r})"


def divide(a: float, b: float) -> float:
    """Division that cannot take the show down: anything over zero reads zero.

    A field's value is only known per vertex per frame, so a divisor that
    happens to reach 0 would otherwise raise mid-render.
    """
    return a / b if b else 0.0


def average(*values: float) -> float:
    """The mean of however many values - an operator with no Python symbol.
    """
    return sum(values) / len(values)


def as_field(x: "ScalarField | float") -> ScalarField:
    """A field as itself, a number as a ConstantField, anything else as None."""
    if hasattr(x, "get"):
        return x
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return ConstantField(x)
    return ConstantField(0)


def _combine(op, a: "ScalarField | float", b: "ScalarField | float") -> ScalarField:
    a, b = as_field(a), as_field(b)
    # NotImplemented, not an exception: Python then raises the usual TypeError,
    # naming both sides, rather than us failing per-vertex at render time.
    if a is None or b is None:
        return NotImplemented
    return CombinedField(op, a, b, False)

# How much of a new second's numbers shows up in the smoothed ones. A third
# settles in about three seconds, which is slow enough to read off a screen
# and quick enough to show a knob being turned.
SMOOTH = 1 / 3

# Stands in for "no reading yet" while looking for the smallest. Any real one
# is smaller.
FOREVER = 1 << 62


@dataclass
class Timing:
    """How long a slot's gets are taking, in microseconds.

    The four numbers describe the gets of one second - the worst, the best,
    the mean, and how far they spread either side of it - and each is then
    smoothed across seconds, so what comes out is steady enough to read
    rather than jumping about with whichever end happened to be slowest.

    `calls` is that second's count, left raw. It is what turns a mean into a
    load: a slot averaging 2us over 2,600 gets is spending 5ms a second.
    """

    max: float = 0.0
    min: float = 0.0
    mean: float = 0.0
    sd: float = 0.0
    calls: int = 0


class Slot(ScalarField):
    """A mutable cell an effect owns, holding whatever field drives it.

    The effect declares one per input and reads it like any other field:

        class Pluck(Effect):
            def __init__(self):
                self.amp = Slot("amp")

            def render(self, now, lattice, graph):
                self.amp.get(now, end)

    It is a ScalarField itself, so it needs no unwrapping and can be combined
    like one. Being mutable, what drives a slot can be changed while running.
    """

    def __init__(self, name: str = ""):
        self.name = name
        self._field: ScalarField = ConstantField(0)

        # Whether what is in here has already been seen to raise. A field that
        # fails does so per end per frame, so the first one says what happened
        # and the rest are silent; plugging something else in arms it again.
        self._failed = False

        # What the gets of this second have cost, as running totals rather
        # than a list of them: a get happens once per end per frame, so
        # nothing on that path may allocate. Keeping the squares as well as
        # the total is what gives the spread without keeping the samples.
        #
        # Nanoseconds, and they stay small enough to be machine integers: a
        # million gets a second of a hundred microseconds each would still
        # square and sum to 1e16, inside the 9.2e18 a 64-bit integer holds, so
        # none of this falls back on big arithmetic.
        self._calls = 0
        self._spent = 0
        self._squares = 0
        self._worst = 0
        self._best = FOREVER

        # The smoothed numbers, or None until a second has gone by with
        # something in it - the first fold seeds them rather than ramping up
        # from zero.
        self.timing: Timing | None = None

    def set(self, field: "ScalarField | float") -> ScalarField:
        """Plug a field (or a constant) in, replacing whatever was there."""
        resolved = as_field(field)
        if resolved is None:
            raise TypeError(
                f"slot {self.name!r} takes a ScalarField or a number,"
                f" not {type(field).__name__}"
            )
        self._field = resolved
        self._failed = False
        return resolved

    def clear(self):
        """Unplug whatever is in here, back to how it started."""
        self._field = ConstantField(0)
        self._failed = False

    @property
    def field(self) -> ScalarField:
        """What is plugged in"""
        return self._field

    @property
    def connected(self) -> bool:
        return True

    def get(self, now: Event, end: EndRef) -> float:
        start = perf_counter_ns()

        # Catch exceptions from evaluating fields, log them once until the field is re-set.
        try:
            value = self._field.get(now, end)
        except Exception:
            value = 0.0

            if not self._failed:
                self._failed = True
                print(f"slot {self.name!r} raised - reading 0 until something"
                      f" else is plugged in:")
                traceback.print_exc()

        took = perf_counter_ns() - start

        self._calls += 1
        self._spent += took
        self._squares += took * took

        if took > self._worst:
            self._worst = took

        if took < self._best:
            self._best = took

        return value

    def fold(self) -> Timing | None:
        """Fold the gets since the last fold into the smoothed numbers, and
        start the next second's count.

        None when nothing asked this slot for anything, which is how a slot
        that is not being computed drops out of the stats rather than
        reporting a stale second.
        """
        calls = self._calls

        if not calls:
            return None

        mean = self._spent / calls

        # The spread without keeping the samples: the mean of the squares less
        # the square of the mean. Floating point can undershoot that to a
        # hair below zero when every get took the same time, hence the clamp.
        spread = max(self._squares / calls - mean * mean, 0.0) ** 0.5

        was = self.timing
        fresh = Timing(self._worst / 1000, self._best / 1000,
                       mean / 1000, spread / 1000, calls)

        self.timing = fresh if was is None else Timing(
            max=was.max + SMOOTH * (fresh.max - was.max),
            min=was.min + SMOOTH * (fresh.min - was.min),
            mean=was.mean + SMOOTH * (fresh.mean - was.mean),
            sd=was.sd + SMOOTH * (fresh.sd - was.sd),
            calls=calls,
        )

        self._calls = self._spent = self._squares = self._worst = 0
        self._best = FOREVER

        return self.timing

    def __repr__(self) -> str:
        return f"Slot({self.name!r} -> {self._field!r})"
