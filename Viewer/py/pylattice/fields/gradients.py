"""Colour gradients: a hue and a saturation for every place along 0..1.

A gradient is a few stops, each a hue and a saturation at a place along 0..1.
A field that runs 0..1 - a knob, a wipe, a ripple - says where along it to be,
and the gradient says what colour that is. Value is not part of a gradient: how
bright something is stays with whatever draws it.

A knob picks a gradient by its *position*, a number the gradient is written
down at. It is written down rather than worked out from an order so that adding
a gradient never moves another a knob already points at - the same reason a
`CustomChoice` indexes the CC directly (docs/CONTROLS.md).

Where gradients come from is all this knows about:

- The ones declared in code (`instrument/gradients.py`), usable by every preset.
- The ones a preset carries in its own file, laid over those while it plays. On
  a shared position the preset's wins. That is the whole rule: which positions
  and names a preset *should* use, and what makes a stop list sensible, is for
  whatever writes the preset - the UI - to decide.
"""

from collections.abc import Iterable
from dataclasses import dataclass

# (frac, hue, sat), each 0-1. Plain tuples so a gradient reads the same in code
# and as JSON, where it is an array of three numbers.
Stop = tuple[float, float, float]

CC_COUNT = 128


def gradient_hs(stops, t):
    """Sample a (frac, hue, sat) gradient at t, returning (hue, sat).

    stops: [(frac, hue, sat), ...] sorted by frac, hue and sat in 0-1.
    Each segment is eased with smoothstep, like interp_points. Two stops with
    the same frac make a hard step there. t outside the range clamps to the
    first or last stop. Value is not part of the gradient.
    """
    if t <= stops[0][0]:
        return stops[0][1], stops[0][2]
    for (f0, h0, s0), (f1, h1, s1) in zip(stops, stops[1:]):
        if f0 <= t < f1:
            u = (t - f0) / (f1 - f0)
            k = u * u * (3 - 2 * u)  # smoothstep
            return h0 + (h1 - h0) * k, s0 + (s1 - s0) * k
    return stops[-1][1], stops[-1][2]


@dataclass(frozen=True)
class Gradient:
    """A named gradient, and the position on a knob that picks it."""

    name: str
    position: int
    stops: tuple[Stop, ...]

    def at(self, t: float) -> tuple[float, float]:
        """(hue, sat) at t."""
        return gradient_hs(self.stops, t)


class GradientLibrary:
    """The gradients a knob can land on: the declared ones, and whatever the
    playing preset lays over them.

    Long-lived and shared by every operator that reads a gradient, so what a
    knob means follows the preset: applying a patch installs its gradients, and
    the next frame reads them.

    A knob lands on whichever gradient is *nearest* a position one is at, the
    way a `CustomChoice` reads its knob, so every value from 0 to 127 means
    something. The table is worked out when the set changes, because `at` is
    asked once per end per frame and may not search.
    """

    def __init__(self, declared: Iterable[Gradient] = ()):
        self._declared = tuple(declared)
        self._table: tuple[Gradient | None, ...] = ()
        self.load(())

    @property
    def declared(self) -> tuple[Gradient, ...]:
        return self._declared

    def load(self, gradients: Iterable[Gradient]):
        """Rebuild from the declared gradients plus this preset's own. Nothing of
        the last preset's is kept. On a shared position the preset's is used."""
        by_position = {g.position: g for g in self._declared}
        by_position.update((g.position, g) for g in gradients)

        if not by_position:
            self._table = (None,) * CC_COUNT
            return

        # Nearest position there is one at; a tie goes to the lower.
        positions = sorted(by_position)
        self._table = tuple(
            by_position[min(positions, key=lambda p: (abs(p - value), p))]
            for value in range(CC_COUNT)
        )

    def at(self, value: int) -> Gradient | None:
        """The gradient a knob at `value` (0-127) is on, or None if there are
        none at all."""
        return self._table[min(max(int(value), 0), CC_COUNT - 1)]
