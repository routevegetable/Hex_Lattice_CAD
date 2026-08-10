"""Example: port of the CircuitPython rig's fast_lightning() and
color_temp_lightning_edges() (program.py on the board) to the lattice
simulation, using the flat Pixels/sendChannels API (see four_colors.py)
rather than ModuleFrame/the graph API.

WHAT THE RIG DID
-----------------
The board drove one physical hexagon with 6 edges (num_edges=6), each edge 8
LEDs wired as 4 "pairs" (PAIRS in config.py) x 2 sides, addressed as one flat
48-pixel strip (pixel index = edge * 8 + PAIRS[pair_ix][side]). fast_lightning()
plays a scripted brightness envelope - measured frame-by-frame off a real
lightning video (_FAST_LIGHTNING_BURSTS below) - independently on each of
that hexagon's 6 edges, each edge striking on its own random repeat timer,
each of its 8 LEDs flickering on/off around the envelope's current level
rather than tracking it smoothly. color_temp_lightning_edges() is a thin
wrapper: it doesn't add any new lighting logic, it just fixes each edge's
color to a position on a red -> blue gradient (red_edge is pure red, the
opposite edge is almost blue, everything between interpolates by angular
distance) and makes edges near red_edge strike more often than edges near
the blue end, by handing fast_lightning per-edge edge_colors/
edge_repeat_every_secs dicts.

TRANSLATING TO THIS MODULE'S API - CONCERNS
---------------------------------------------
1. Pixels/sendChannels bypasses ModuleFrame entirely - same as four_colors.py,
   this writes 48 raw (r, g, b) ints into channel 0 and ships them with
   sendChannels, rather than going through ModuleFrame.serialize's 4-channel/
   CHANNEL_EDGES layout. That means it renders correctly in the browser only
   if whatever is on the other end of a given (x, y) location treats channel
   0 as a flat 48-pixel strip the way this script does - the lite viewer's
   own rendering path (frame.ts ModuleFrame.deserialize) expects the real
   4-channel/CHANNEL_EDGES split instead, so this won't visually decode
   there today. It matches how four_colors.py already talks to the socket,
   so this follows that established (if not yet viewer-verified) approach
   rather than inventing a different one.
2. One hexagon, one location. Because it's a flat 48-pixel buffer with no
   edge/module addressing beyond that, there's no version of "which physical
   hex is this" beyond the (x, y) location passed to sendChannels - so this
   targets a single module, MODULE_X/MODULE_Y below (0-0 by default). Driving
   more than one location just needs its own fast_lightning() state (and its
   own sendChannels call) per (x, y) you want lit - straightforward, just
   more RNG/CPU per location.
3. Sample rate. The rig called its frame() function (and pushed to the strip)
   every tick=0.01s, 100/sec - important because the flicker timing
   (flicker_hold_secs/off_hold_secs default down to 8ms) re-rolls only when
   frame() runs. This script paces sends at FPS below over UDP multicast
   instead; the envelope math is still computed from wall-clock
   time.monotonic() so nothing drifts, but flicker transitions can only
   resolve as finely as FPS allows. Defaulted to 60fps as a compromise;
   raise it if the flicker reads too chunky, at the cost of more UDP
   sends/sec.
4. pattern= only supports fast_lightning. The rig's color_temp_lightning_edges
   could also drive fast_lightning_held, hot_zap, recorded_pattern, or
   recorded_pattern_held - none of those are ported here, so `pattern` is
   kept as a parameter (for API fidelity / a future port) but fast_lightning
   is the only value that currently works.

    1. python3 serve.py                 # creates the socket + serves the viewer
    2. python3 py/examples/color_temp_lightning_edges.py

Env: HINGE_SOCK overrides the socket path (LatticeClient resolves it).
"""
import os
import random
import sys
import time

# Make the repo root importable so `py.lib` resolves.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from py.lib import LatticeClient   # noqa: E402

MODULE_X = 0      # target module location (lateral)
MODULE_Y = 0      # target module location (height)
FPS = 60          # see concern #3 above - the rig's own tick was 100/sec
RED_EDGE = 0      # which of the 6 edges (0-5) is "pure red"

# ---- ported from the rig's config.py ---------------------------------------
PAIRS = [[0, 5], [1, 4], [2, 7], [3, 6]]
NUM_EDGES = 6
PIXELS_PER_EDGE = len(PAIRS) * 2   # 8


# ---- same Pixels wrapper as four_colors.py: a channel-0 pixel buffer with
# show() to push it over sendChannels -----------------------------------------
class Pixels:
    """List-like wrapper around a channel-0 pixel buffer, with show() to push it."""

    def __init__(self, client: LatticeClient, count: int, x: int = 0, y: int = 0):
        self._client = client
        self._x = x
        self._y = y
        self._data = [(0, 0, 0)] * count

    def __len__(self) -> int:
        return len(self._data)

    def __getitem__(self, i):
        return self._data[i]

    def __setitem__(self, i, value) -> None:
        self._data[i] = value

    def show(self) -> None:
        self._client.sendChannels(self._x, self._y, [self._data, [], [], []])


class PixelPairs:
    """Direct port of the rig's animation.py PixelPairs, addressing a flat
    Pixels buffer (edge * PIXELS_PER_EDGE + PAIRS[pair_ix][side]) instead of
    a raw neopixel strip - same shape fast_lightning/color_temp_lightning_edges
    already expect (set_side/set with an edge= kwarg).
    """

    def __init__(self, pixels: Pixels):
        self.pixels = pixels

    def set_side(self, pair_ix, side, col, edge=None):
        idx = PAIRS[pair_ix][side]
        edges = range(NUM_EDGES) if edge is None else (edge,)
        for e in edges:
            self.pixels[e * PIXELS_PER_EDGE + idx] = col

    def set(self, pair_ix, col_a, col_b=None, edge=None):
        if col_b is None:
            col_b = col_a
        self.set_side(pair_ix, 0, col_a, edge)
        self.set_side(pair_ix, 1, col_b, edge)


# ---- ported from the rig's colors.py: color-temperature gradients ---------
def smoothstep(t: float) -> float:
    return t * t * (3 - 2 * t)


def _interp(v0, v1, a0, a1, v):
    if v >= v1:
        return a1
    if v < v0:
        return a0
    return int(a0 + (a1 - a0) * smoothstep((v - v0) / (v1 - v0)))


def interp_points(pts, v):
    pc, pcl, pvl, pv = (0, 0, 0), (0, 0, 0), 0, 0
    for pv, pc in pts:
        if pv > v:
            break
        pvl, pcl = pv, pc
    rl, gl, bl = pcl
    r, g, b = pc
    return (_interp(pvl, pv, rl, r, v), _interp(pvl, pv, gl, g, v), _interp(pvl, pv, bl, b, v))


COLOR_TEMP_BRIGHT_SEQ = [
    (0.0, (255, 0, 0)),
    (0.4, (255, 60, 0)),
    (0.6, (255, 180, 120)),
    (0.7, (255, 255, 255)),
    (1.0, (10, 20, 255)),
]

COLOR_TEMP_MUTED_SEQ = [
    (0.0, (255, 0, 0)),
    (0.23, (255, 60, 0)),
    (0.38, (140, 120, 100)),
    (0.8, (60, 80, 120)),
    (1.0, (10, 20, 255)),
]


def color_temp_bright(fraction: float):
    return interp_points(COLOR_TEMP_BRIGHT_SEQ, fraction)


def color_temp_muted(fraction: float):
    return interp_points(COLOR_TEMP_MUTED_SEQ, fraction)


# ---- ported from the rig's helper.py ---------------------------------------
def hyperbolic_ease_in(fraction, epsilon=0.111):
    def decay(x):
        return 1 / ((1 - x) + epsilon)

    start, end = decay(0), decay(1)
    return (decay(fraction) - start) / (end - start)


def _jitter_color(col, amount):
    return tuple(max(0, min(255, c + random.randint(-amount, amount))) for c in col)


def _interp_keyframes(keyframes, t):
    if t <= keyframes[0][0]:
        return keyframes[0][1]
    if t >= keyframes[-1][0]:
        return keyframes[-1][1]
    for (t0, v0), (t1, v1) in zip(keyframes, keyframes[1:]):
        if t0 <= t <= t1:
            return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return 0.0


# measured directly from fast-light.mp4, frame by frame (top-5%-brightest-pixel
# mean of each frame, normalized 0-1) - verbatim from the rig, see program.py.
# Each tuple is (burst_start_sec, [(t_since_burst_start, level_0_1), ...]).
_FAST_LIGHTNING_BURSTS = [
    (0.000, [(0.000, 0.00), (0.033, 0.33), (0.067, 0.23), (0.100, 0.00)]),
    (
        0.268,
        [
            (0.000, 0.00), (0.033, 0.25), (0.067, 0.56), (0.100, 0.79),
            (0.135, 0.93), (0.200, 0.95), (0.400, 0.94), (0.600, 0.87),
            (0.635, 0.73), (0.669, 0.51), (0.702, 0.57), (0.736, 0.38),
            (0.769, 0.33), (0.803, 0.34), (0.836, 0.35), (0.869, 0.45),
            (0.903, 0.42), (0.935, 0.51), (0.969, 0.51), (1.002, 0.49),
            (1.035, 0.40), (1.069, 0.47), (1.102, 0.24), (1.135, 0.00),
        ],
    ),
    (
        1.537,
        [
            (0.000, 0.00), (0.033, 0.33), (0.067, 0.35), (0.100, 0.37),
            (0.133, 0.51), (0.167, 0.42), (0.201, 0.34), (0.234, 0.47),
            (0.268, 0.51), (0.301, 0.27), (0.334, 0.00),
        ],
    ),
    (
        1.905,
        [
            (0.000, 0.00), (0.033, 0.14), (0.067, 0.32), (0.100, 0.31),
            (0.134, 0.49), (0.167, 0.45), (0.201, 0.37), (0.234, 0.40),
            (0.268, 0.43), (0.301, 0.19), (0.334, 0.00),
        ],
    ),
]
_FAST_LIGHTNING_DURATION = 2.3


def fast_lightning(
    pixel_pairs,
    edges=None,
    color=color_temp_bright,
    edge_colors=None,
    color_sweep_secs=0.18,
    repeat_every_secs=(3, 7),
    edge_repeat_every_secs=None,
    strike_brightness_range=(0.6, 1.8),
    strike_brightness_skew=3,
    fiber_gain_range=(0.8, 1.0),
    fiber_offset_secs=0.015,
    flicker_hold_secs=(0.015, 0.04),
    off_hold_secs=(0.008, 0.02),
    jitter=15,
    speed=1.0,
    cluster_duration=None,
):
    """Build the per-tick frame() for the hexagon. TUNABLE PARAMETERS:

    pixel_pairs: a PixelPairs wrapping a Pixels buffer - the one addition vs.
        the rig's API, which wrote to a single global pixel_pairs instead.
    edges: which of the hexagon's 6 edges (0-5) animate. None (default) means
        every edge; pass an int or list to restrict it. Each edge gets its
        own independent fiber set and strike scheduler, so edges strike at
        their own random times rather than in lockstep.
    color: a gradient function (fraction 0-1 -> RGB, like color_temp_bright/
        muted) or a plain fixed (r, g, b) color, applied to every edge in
        `edges` not overridden in edge_colors. With a gradient, every burst
        restarts its own sweep from fraction 0 (red) toward 1 (blue) over
        color_sweep_secs - onset reads warm, tail reads cool, resetting on
        the next burst. With a plain color every burst just stays that color.
    edge_colors: {edge_index: color_or_gradient} - per-edge override of
        `color`. This is how color_temp_lightning_edges (below) paints each
        edge its own spot on the red->blue gradient.
    color_sweep_secs: how long (seconds) each burst's color sweep from red to
        the gradient's blue end takes. Only matters if `color` is a gradient.
    repeat_every_secs: (lo, hi) random range for how long an edge waits
        (fully dark) after one strike finishes before its next one starts.
    edge_repeat_every_secs: {edge_index: (lo, hi)} - per-edge override of
        repeat_every_secs, letting specific edges strike more/less often.
    strike_brightness_range / strike_brightness_skew: every strike rolls its
        own brightness multiplier from strike_brightness_range, skewed
        toward the low end by strike_brightness_skew (higher = rarer big
        strikes). Values above 1.0 push lit fibers toward (and clamp at)
        full brightness on the rare big ones.
    fiber_gain_range / fiber_offset_secs: per-fiber variation so an edge's 8
        LEDs don't move in perfect lockstep - a brightness ceiling
        (fiber_gain_range) and a small timing offset (+/- fiber_offset_secs)
        rolled once per fiber at startup.
    flicker_hold_secs / off_hold_secs: how long a fiber holds once it rolls
        lit (flicker_hold_secs) vs. dark (off_hold_secs) before re-rolling
        on/off again, with the odds and brightness of each roll tracking the
        envelope's current level. off_hold_secs is shorter by default, so a
        fiber that rolls dark snaps back to lit again almost immediately -
        reads as a quick blackout blip rather than a slow fade. Shorten both
        together for busier, all-over flicker.
    jitter: +/- per-channel color jitter (see _jitter_color) applied to every
        lit fiber, for shade variation instead of flat, identical color.
    speed: scales how fast each burst's own envelope/color-sweep plays out
        (2.0 = twice as fast) without moving burst start times or overall
        cluster length. A sped-up burst loops within its slot instead of
        going dark early.
    cluster_duration: stretches/compresses the OUTER timeline (burst start
        times and overall cluster length) instead of each burst's own shape.
        None (default) keeps the measured ~2.3s length.
    """
    if edges is None:
        edges = range(NUM_EDGES)
    elif isinstance(edges, int):
        edges = (edges,)

    def _gradient_for(edge):
        c = (edge_colors or {}).get(edge, color)
        return c if callable(c) else (lambda fraction, cc=c: cc)

    def _repeat_range_for(edge):
        return (edge_repeat_every_secs or {}).get(edge, repeat_every_secs)

    def _roll_strike_brightness():
        lo, hi = strike_brightness_range
        return lo + (hi - lo) * (random.random() ** strike_brightness_skew)

    cluster_scale = (
        1.0 if cluster_duration is None else cluster_duration / _FAST_LIGHTNING_DURATION
    )
    scaled_duration = _FAST_LIGHTNING_DURATION * cluster_scale

    edge_state = {}
    for edge in edges:
        edge_state[edge] = {
            "gradient": _gradient_for(edge),
            "strike_start": time.monotonic() + random.uniform(*_repeat_range_for(edge)),
            "strike_brightness": _roll_strike_brightness(),
            "fibers": [
                {
                    "gain": random.uniform(*fiber_gain_range),
                    "offset": random.uniform(-fiber_offset_secs, fiber_offset_secs),
                    "lit": False,
                    "next_roll": 0.0,
                }
                for _ in range(len(PAIRS) * 2)
            ],
        }

    def frame():
        now = time.monotonic()
        for edge, es in edge_state.items():
            t = now - es["strike_start"]
            if t >= scaled_duration:
                es["strike_start"] = now + random.uniform(*_repeat_range_for(edge))
                es["strike_brightness"] = _roll_strike_brightness()
                t = -1.0
            gradient = es["gradient"]
            fibers = es["fibers"]
            strike_brightness = es["strike_brightness"]

            for i in range(len(PAIRS)):
                cols = []
                for side in (0, 1):
                    fiber = fibers[i * 2 + side]
                    ft = t - fiber["offset"]
                    target = 0.0
                    since_reset = None
                    for burst_start, keyframes in _FAST_LIGHTNING_BURSTS:
                        bt = ft - burst_start * cluster_scale
                        if 0 <= bt <= keyframes[-1][0] * cluster_scale:
                            burst_len = keyframes[-1][0]
                            bt_natural = ((bt / cluster_scale) * speed) % burst_len
                            target = _interp_keyframes(keyframes, bt_natural)
                            since_reset = bt_natural
                            break
                    if since_reset is None:
                        fiber["lit"] = False
                        fiber["next_roll"] = 0.0
                        col = (0, 0, 0)
                    else:
                        if ft >= fiber["next_roll"]:
                            fiber["lit"] = random.random() < target
                            fiber["next_roll"] = ft + random.uniform(
                                *(flicker_hold_secs if fiber["lit"] else off_hold_secs)
                            )
                        level = (
                            fiber["gain"] * max(target, 0.5) * strike_brightness
                            if fiber["lit"]
                            else 0.0
                        )
                        fraction = min(1.0, since_reset / color_sweep_secs)
                        col = tuple(
                            min(255, int(c * level))
                            for c in _jitter_color(gradient(fraction), jitter)
                        )
                    cols.append(col)
                pixel_pairs.set(i, cols[0], cols[1], edge=edge)

    return frame


def color_temp_lightning_edges(
    pixel_pairs,
    gradient=color_temp_muted,
    epsilon=0.111,
    red_edge=RED_EDGE,
    red_repeat_every_secs=(0.5, 2),
    blue_repeat_every_secs=(6, 14),
    pattern=fast_lightning,
    **pattern_kwargs,
):
    """Build the per-tick frame() for the hexagon, each edge colored by its
    position on a red->blue gradient. TUNABLE PARAMETERS:

    pixel_pairs: same PixelPairs as fast_lightning above.
    gradient: fraction (0-1) -> RGB. Defaults to color_temp_muted (dimmer,
        less blown-out than color_temp_bright - tuned for how much of the
        range sits near the low/red end, see epsilon below).
    epsilon: warps how fractions map to gradient position (hyperbolic_ease_in)
        so edges near red_edge linger closer to pure red instead of the
        red->blue sweep being evenly spaced by angle. Smaller epsilon = more
        of the hexagon reads red before rushing to blue near the far edge.
    red_edge: which edge (0-5) is fraction 0 / pure red. The opposite edge
        (3 steps away on this 6-edge hexagon) lands at fraction 1 / almost
        blue; the rest fall in between by angular distance.
    red_repeat_every_secs / blue_repeat_every_secs: (lo, hi) strike-repeat
        ranges for the red_edge and its opposite edge, respectively - edges
        between interpolate both ends of these ranges by the same fraction
        used for color, so edges near red strike often and edges near blue
        strike rarely.
    pattern: which per-edge flash function to drive. Only fast_lightning is
        ported here (see concern #4 in the module docstring) - kept as a
        parameter for fidelity with the rig's API.
    **pattern_kwargs: passed straight through to `pattern` - e.g.
        color_sweep_secs, jitter, speed, strike_brightness_range, everything
        fast_lightning takes above except edges/edge_colors/
        edge_repeat_every_secs, which this function computes itself.
    """
    half = NUM_EDGES / 2

    def edge_fraction(edge):
        delta = abs(edge - red_edge) % NUM_EDGES
        angular_dist = min(delta, NUM_EDGES - delta)
        return hyperbolic_ease_in(angular_dist / half, epsilon)

    fractions = {edge: edge_fraction(edge) for edge in range(NUM_EDGES)}
    edge_colors = {edge: gradient(f) for edge, f in fractions.items()}

    edge_repeat_every_secs = {
        edge: (
            red_repeat_every_secs[0]
            + (blue_repeat_every_secs[0] - red_repeat_every_secs[0]) * f,
            red_repeat_every_secs[1]
            + (blue_repeat_every_secs[1] - red_repeat_every_secs[1]) * f,
        )
        for edge, f in fractions.items()
    }

    return pattern(
        pixel_pairs,
        edges=range(NUM_EDGES),
        edge_colors=edge_colors,
        edge_repeat_every_secs=edge_repeat_every_secs,
        **pattern_kwargs,
    )


def main() -> None:
    client = LatticeClient()      # socket path from HINGE_SOCK / default
    pixels = Pixels(client, NUM_EDGES * PIXELS_PER_EDGE)
    pixel_pairs = PixelPairs(pixels)

    frame = color_temp_lightning_edges(pixel_pairs, red_edge=RED_EDGE, epsilon=.30, speed=.5)

    print(
        f"color_temp_lightning_edges: broadcasting  "
        f"@ {FPS}fps, red_edge={RED_EDGE} (see module docstring for translation concerns)"
    )
    try:
        while True:
            frame()
            client.sendChannels(0, 0, [pixels._data, [], [], []])
            time.sleep(1 / FPS)
    except KeyboardInterrupt:
        client.close()


if __name__ == "__main__":
    main()
