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


def _hue_toward(h0, h1, k):
    """The hue `k` (0-1) of the way from h0 to h1, going the short way round.

    Hue is a circle, so 0.95 to 0.01 is a step of 0.06 through red and not a
    sweep of 0.94 back through every other colour. Exactly opposite hues (0.5 apart)
    go down the wheel, toward lower hues. The result is 0-1, as a hue is wherever it is read.
    """
    delta = (h1 - h0 + 0.5) % 1 - 0.5           # -0.5 <= delta < 0.5
    return (h0 + delta * k) % 1


# A stop paler than this is white. Hue is the direction away from the centre of the
# colour wheel, and at the centre there is none, so a stop that close has no hue worth
# keeping: a stop nearly white is exactly white, whatever hue it was dragged in.
WHITE_BELOW = 0.1


def _white_aware(h0, s0, h1, s1):
    """The two ends of a segment, with a white one made exactly white and given the
    other end's hue.

    So arriving at white keeps the colour you came from all the way to the centre, and
    leaving it heads straight for the colour you are going to, with no detour through
    whatever hue the white stop happened to be carrying. Two white ends stay white.
    """
    white0, white1 = s0 < WHITE_BELOW, s1 < WHITE_BELOW

    if white0:
        s0 = 0.0
    if white1:
        s1 = 0.0

    if white0 and not white1:
        h0 = h1
    elif white1 and not white0:
        h1 = h0

    return h0, s0, h1, s1


def gradient_hs(stops, t):
    """Sample a (frac, hue, sat) gradient at t, returning (hue, sat).

    stops: [(frac, hue, sat), ...] sorted by frac, hue and sat in 0-1.
    Each segment is eased with smoothstep, like interp_points. Hue goes the short
    way round the wheel between two stops, so pink to orange passes through red,
    not through every other colour; saturation is a plain blend. A stop paler than
    WHITE_BELOW is white and takes the hue of the stop beside it (see
    `_white_aware`). Two stops with the same frac make a hard step there. t outside
    the range clamps to the first or last stop. Value is not part of the gradient.
    """
    if t <= stops[0][0]:
        _, h, s = stops[0]
        return h, (0.0 if s < WHITE_BELOW else s)

    for (f0, h0, s0), (f1, h1, s1) in zip(stops, stops[1:]):
        if f0 <= t < f1:
            h0, s0, h1, s1 = _white_aware(h0, s0, h1, s1)
            u = (t - f0) / (f1 - f0)
            k = u * u * (3 - 2 * u)  # smoothstep
            return _hue_toward(h0, h1, k), s0 + (s1 - s0) * k

    _, h, s = stops[-1]
    return h, (0.0 if s < WHITE_BELOW else s)


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
