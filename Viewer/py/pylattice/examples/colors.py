import math
from pylattice.examples.tempo import Event, psweep


YELLOW_ROSE = [ # three yellowish-reddish shades of white 
    [1, .8, .8,],
    [.8, .8, .6],
    [.9, .8, .6]

    ]

def vary(now: Event, start: float, end: float, period: int, offset: float) -> float:
    rads = psweep(now, period, 0, 2 * 3.141, offset)

    y = (math.sin(rads + (offset * 2 * 3.141)) / 2) + 0.5 # 0 to 1, starting at 0.5

    range = end - start

    output_offset = range * y
    return start + output_offset


def hsv(h: float, s: float, v: float) -> tuple[float,float,float]:
    h = (h % 1 + 1) % 1
    i = int(h * 6)
    f = h * 6 - i
    p, q, u = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    return [(v, u, p), (q, v, p), (p, v, u), (p, q, v), (u, p, v), (v, p, q)][i % 6]