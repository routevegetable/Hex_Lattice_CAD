"""Colour gradients: a hue and a saturation for every place along 0..1.

A gradient is a few stops, each a hue and a saturation at a place along 0..1.
A field that runs 0..1 - a knob, a wipe, a ripple - says where along it to be,
and the gradient says what colour that is. Value is not part of a gradient: how
bright something is stays with whatever draws it.

A knob picks a gradient by an index, 0-127, and is on the gradient at exactly
that index, or on none where nothing is. Indexes 0-63 are the gradients declared
in code (`instrument/gradients.py`), by their order in that list. Indexes 64-127
are the playing preset's own, by their order in its `gradients` list: 64 is its
first, 65 its second. So an index means one gradient whatever preset is playing
for 0-63, and the preset's own for 64-127.

An order is only a safe address if it never changes, so a list that is indexed
like this is append-only: nothing is removed or moved, or every knob that points
past it points at something else. See `instrument/gradients.py`.
"""

from dataclasses import dataclass
from functools import cached_property

# (frac, hue, sat), each 0-1. Plain tuples so a gradient reads the same in code
# and as JSON, where it is an array of three numbers.
Stop = tuple[float, float, float]

# How a knob's 0-127 is shared out: the declared gradients first, then the playing
# preset's own.
GLOBAL_SLOTS = 64
OWN_FIRST = 64
OWN_SLOTS = 64


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


@dataclass
class GradientDef:
    """A gradient as written down: a name, and its stops.

    The name is only for whoever is reading it. Where a knob must sit to pick the
    gradient is its place in the list it is kept in, not something it carries.
    """

    name: str
    stops: list[Stop]

    @cached_property
    def _sorted(self) -> list[Stop]:
        # Sorted by frac, which `gradient_hs` relies on. The sort is stable, so
        # a hard step keeps its two sides. Once, not on every sample.
        return sorted((tuple(s) for s in self.stops), key=lambda s: s[0])

    def at(self, t: float) -> tuple[float, float]:
        """(hue, sat) at t."""
        return gradient_hs(self._sorted, t)
