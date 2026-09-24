"""What a field is: the protocols it implements, and how fields combine."""
import operator
from typing import Protocol

from pylattice.examples.tempo import Event
from pylattice.frame import RGB
from pylattice.graph import EndRef


class ScalarField(Protocol):
    """
    Something that has a value for each end.
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


class ColorField(Protocol):
    """
    Something that has a color for each end.
    """
    def get(self, now: Event, end: EndRef) -> RGB: ...


class ConstantField(ScalarField):
    """The same value at every end - what a number becomes in a combination."""

    def __init__(self, value: float):
        self._value = float(value)

    def get(self, now: Event, end: EndRef) -> float:
        return self._value

    def __repr__(self) -> str:
        return f"ConstantField({self._value})"


class CombinedField(ScalarField):
    """Two fields under an operator, evaluated at the same end."""

    def __init__(self, op, a: ScalarField, b: ScalarField):
        self._op = op
        self._a = a
        self._b = b

    def get(self, now: Event, end: EndRef) -> float:
        return self._op(self._a.get(now, end), self._b.get(now, end))

    def __repr__(self) -> str:
        return f"({self._a!r} {self._op.__name__} {self._b!r})"


def as_field(x: "ScalarField | float") -> ScalarField | None:
    """A field as itself, a number as a ConstantField, anything else as None."""
    if hasattr(x, "get"):
        return x
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return ConstantField(x)
    return None


def _combine(op, a: "ScalarField | float", b: "ScalarField | float") -> ScalarField:
    a, b = as_field(a), as_field(b)
    # NotImplemented, not an exception: Python then raises the usual TypeError,
    # naming both sides, rather than us failing per-vertex at render time.
    if a is None or b is None:
        return NotImplemented
    return CombinedField(op, a, b)


class UnconnectedSlot(RuntimeError):
    """An effect read a slot that nothing has been plugged into."""


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

    def __init__(self, name: str = "", field: "ScalarField | float | None" = None):
        self.name = name
        self._field: ScalarField | None = None
        if field is not None:
            self.set(field)

    def set(self, field: "ScalarField | float") -> ScalarField:
        """Plug a field (or a constant) in, replacing whatever was there."""
        resolved = as_field(field)
        if resolved is None:
            raise TypeError(
                f"slot {self.name!r} takes a ScalarField or a number,"
                f" not {type(field).__name__}")
        self._field = resolved
        return resolved

    @property
    def field(self) -> ScalarField | None:
        """What is plugged in, if anything."""
        return self._field

    @property
    def connected(self) -> bool:
        return self._field is not None

    def get(self, now: Event, end: EndRef) -> float:
        if self._field is None:
            raise UnconnectedSlot(f"slot {self.name!r} has nothing plugged into it")
        return self._field.get(now, end)

    def __repr__(self) -> str:
        return f"Slot({self.name!r} -> {self._field!r})"
