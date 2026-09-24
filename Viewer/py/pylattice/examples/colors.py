from dataclasses import dataclass
import math
from pylattice.frame import ModuleEdge, ModuleFrame
from pylattice.examples.tempo import Event, psweep


def vary(now: Event, start: float, end: float, period: int, offset: float) -> float:
    rads = psweep(now, period, 0, 2 * 3.141, offset)

    y = (math.sin(rads + (offset * 2 * 3.141)) / 2) + 0.5  # 0 to 1, starting at 0.5

    range = end - start

    output_offset = range * y
    return start + output_offset


def transition(t: float, rads: float = 0.5) -> float:
    """
    Transition from 0 to 1 over a quarter-sine wave.
    Pass rads=1 to sweep from 0 to 1 and back.
    """
    t = max(0.0, min(1.0, t))
    return math.sin(t * rads * math.pi)


def hsv(h: float, s: float, v: float) -> tuple[float, float, float]:
    h = (h % 1 + 1) % 1
    i = int(h * 6)
    f = h * 6 - i
    p, q, u = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    return [(v, u, p), (q, v, p), (p, v, u), (p, q, v), (u, p, v), (v, p, q)][i % 6]


def blend_paint(mf: ModuleFrame, edge: ModuleEdge, t: float, color_fn) -> None:
    if t <= 0:
        return
    e = mf[edge].ends
    for end_index, end_name in enumerate(("top", "bottom")):
        arr = getattr(e, end_name)
        for f in range(4):
            color = color_fn(end_index, f)
            cur = arr[f]
            arr[f][:] = [a + (b - a) * t for a, b in zip(cur, color)]


Color = tuple[float, float, float]


def lerp_color(start: Color, end: Color, t: float) -> Color:
    return tuple(s + (e - s) * t for s, e in zip(start, end))


@dataclass
class Keyframe:
    at: float  # when the transition to this color is complete (fraction of whole)
    color: (
        tuple[float, float, float] | list[tuple[float, float, float]]
    )  # RGB or list of RGBs
    ease_in: float | None = (
        None  # fraction of whole prior to `at` when transition should start
    )


@dataclass
class ColorTransition:
    module_level: int
    edges: list[ModuleEdge]
    keyframes: list[Keyframe]
    ends: list[str] | None = None


def expand_colors_to_list(
    color: tuple[float, float, float] | list[tuple[float, float, float]],
) -> list[tuple[float, float, float]]:
    if isinstance(color, list):
        return [color[i % len(color)] for i in range(4)]
    else:
        return [color] * 4


def color_at(keyframes: list[Keyframe], frac: float) -> list[Color]:
    """Look up the color(s) for `frac` (0-1) through a transition's keyframes.

    Before the first keyframe or after the last, holds at that keyframe's
    color(s). Between two keyframes, holds the earlier color(s) until
    `ease_in` before the later keyframe's `at` (the whole gap, if `ease_in`
    is None -- the default), then eases sinusoidally into the later
    color(s) via transition().
    """
    keyframes = sorted(keyframes, key=lambda k: k.at)
    frac = max(0.0, min(1.0, frac))

    if frac <= keyframes[0].at:
        return expand_colors_to_list(keyframes[0].color)

    for k0, k1 in zip(keyframes, keyframes[1:]):
        if frac <= k1.at:
            span = k1.at - k0.at
            ease_in = span if k1.ease_in is None else min(max(k1.ease_in, 0), span)
            ease_start = k1.at - ease_in

            if frac < ease_start:
                return expand_colors_to_list(k0.color)

            if ease_in <= 0:
                return expand_colors_to_list(k1.color)

            colors0 = expand_colors_to_list(k0.color)
            colors1 = expand_colors_to_list(k1.color)
            t = transition((frac - ease_start) / ease_in)
            return [lerp_color(c0, c1, t) for c0, c1 in zip(colors0, colors1)]

    return expand_colors_to_list(keyframes[-1].color)


# colors and color groups

ROSE = hsv(0.02, 0.88, 0.6)
BLUE = hsv(0.67, 0.95, 0.4)
ORANGE = hsv(0.06, 0.95, 0.6)
DEEP_ROSE = hsv(0.02, 0.95, 0.4)
DEEP_ORANGE = hsv(0.06, 0.98, 0.4)
LIGHT_BLUE = hsv(0.67, 0.5, 0.8)
ROSY_WHITE = hsv(0.02, 0.7, 0.6)

YELLOW_ROSE = [  # three yellowish-reddish shades of white
    [
        1,
        0.8,
        0.8,
    ],
    [0.8, 0.8, 0.6],
    [0.9, 0.8, 0.6],
]
