"""Example: port of the CircuitPython rig's brightness_cycle() color envelope
(program.py, driven by animation.py's Fader) onto a moving snake pattern
across the simulated honeycomb.

On the rig, brightness_cycle(col_a_range, col_b_range, handoff_level=...)
drives `num_pairs` independent Faders sitting on 4 STATIC filament pairs of
one segment: each fades in from black to a random col_a, hands off to a
random col_b once col_a's rise crosses handoff_level%, then pauses and
repeats with fresh random picks. There's no "static pair" here — the point of
this example is a 3-edge-long snake travelling the lattice's actual edge
graph (EdgeRef/VertexRef from py.lib.graph — the same connectivity the
viewer itself is built from) — so instead of 4 parallel Faders, there's ONE
Fader driving one continuously evolving color, exactly brightness_cycle's
math otherwise (same rise/handoff/pause/eased-brightness curve). Each time
the snake's head steps to the next edge it grabs a fresh snapshot of that
Fader's current color; the two trailing edges just keep replaying their own
snapshot at a fixed fraction of its brightness (dimmer the older it is),
dropping off after 3 edges — a plain trailing fade, not a re-fade.

Everything here is a 0-255 RGB value written straight to an edge's top/bottom
ends, the same shape of thing the board's own frame() writes to
pixel_pairs.set() — 8 real pixels per edge feeding fiber strands. No
per-frame blending or effect that depends on being in a browser.

    1. python3 serve.py                          # creates the socket + serves the viewer
    2. python3 py/examples/brightness_cycle_snake.py

The snake's path is sized to whatever's actually built in the viewer: every
build() there POSTs its {levels, perRow} to serve.py's /lattice-shape, which
this fetches at startup and re-checks every SHAPE_POLL_SECS - so opening the
viewer first (or changing Levels/angles and hitting Rebuild) reshapes the
snake's range without restarting this script. Falls back to a default
DEFAULT_LEVELS x DEFAULT_PER_ROW (matching the viewer's own defaults) if
serve.py hasn't heard from the viewer yet.

Env: HINGE_SOCK overrides the socket path, HINGE_HTTP the shape-fetch base
URL (both resolved by py.lib).
"""
import os
import random
import sys
import time

# Make the repo root importable so `py.lib` resolves.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from py.lib import ModuleFrame, LatticeClient, EdgeRef, EdgeClass, TileRef, fetch_lattice_shape   # noqa: E402
from py.lib.frame import EDGE_CLASS_TO_MODULE_EDGES   # noqa: E402

FPS = 30
TICK = 1 / FPS

# ---- ported from the rig's colors.py --------------------------------------
VERY_BLUE = ((80, 80), (40, 40), (240, 255))
VERY_GREEN = ((80, 80), (240, 255), (40, 40))


# ---- ported from the rig's helper.py ---------------------------------------
def rand_col(red_range, green_range, blue_range):
    return (random.randint(*red_range), random.randint(*green_range), random.randint(*blue_range))


def lerp_color(start, end, fraction):
    return tuple(int(s + (e - s) * fraction) for s, e in zip(start, end))


def eased_fraction(level):
    return (level / 100) ** 2


def rate_per_tick(rise_ms, tick):
    rise_ticks = (rise_ms / 1000) / tick
    return 100 / rise_ticks


def pause_ticks(pause_length, tick):
    return max(1, int(pause_length / tick))


# ---- ported from the rig's animation.py: Fader, trimmed to a single
# always-both-ends instance (brightness_cycle(very_blue, very_green, ...)
# always supplies col_b_range, so the "b may be absent" branch is dropped).
class ColorFader:
    def __init__(self, col_a_range, col_b_range, fade_from=(0, 0, 0)):
        self.col_a_range = col_a_range
        self.col_b_range = col_b_range
        self.fade_from = fade_from
        self.col_a = rand_col(*col_a_range)
        self.col_b = rand_col(*col_b_range)
        self.a_progress = 0
        self.a_level = 0
        self.a_done = False
        self.b_level = 0
        self.b_rising = True
        self.b_active = False
        self.pause_remaining = 0

    def _restart(self):
        self.col_a = rand_col(*self.col_a_range)
        self.col_b = rand_col(*self.col_b_range)
        self.a_progress = 0
        self.a_level = 0
        self.a_done = False
        self.b_rising = True

    def advance(self, rate, handoff_level, p_ticks):
        if self.pause_remaining > 0:
            self.pause_remaining -= 1
            if self.pause_remaining == 0:
                self._restart()
            return

        if not self.a_done:
            self.a_progress = min(200, self.a_progress + rate)
            self.a_level = self.a_progress if self.a_progress <= 100 else 200 - self.a_progress
            if self.a_progress >= 200:
                self.a_done = True

        if not self.b_active and self.a_progress >= handoff_level:
            self.b_active = True
        if self.b_active:
            if self.b_rising:
                self.b_level = min(100, self.b_level + rate)
                if self.b_level == 100:
                    self.b_rising = False
            else:
                self.b_level = max(0, self.b_level - rate)
                if self.b_level == 0:
                    self.b_active = False

        if self.a_done and not self.b_active and self.b_level == 0:
            self.pause_remaining = p_ticks

    def current_colors(self):
        # a_level/b_level are already 0 during any pause, so this needs no
        # separate "idle" branch - it degrades to fade_from on its own.
        col_a = lerp_color(self.fade_from, self.col_a, eased_fraction(self.a_level))
        col_b = lerp_color(self.fade_from, self.col_b, eased_fraction(self.b_level))
        return col_a, col_b


# ---- brightness_cycle(very_blue, very_green, handoff_level=90) params -----
RISE_MS = 1000
HANDOFF_LEVEL = 90
PAUSE_LENGTH = 2
FADE_FROM = (0, 0, 0)
RATE = rate_per_tick(RISE_MS, TICK)
PAUSE_TICKS = pause_ticks(PAUSE_LENGTH, TICK)

# ---- the snake --------------------------------------------------------------
SNAKE_LEN = 3
TAIL_BRIGHTNESS = [1.0, 0.5, 0.22]      # head -> tail, geometric-ish falloff
STEP_SECS = 0.25                        # how often the head moves to the next edge

# Fallback shape if serve.py has never heard from the viewer (e.g. it hasn't
# been opened yet this run) - matches index.html/lite.html's own defaults.
DEFAULT_LEVELS = 4
DEFAULT_PER_ROW = 9
SHAPE_POLL_SECS = 5     # how often to re-check for a rebuild in the browser

# ModuleEdge (0..11) -> (EdgeClass, tile.x parity) - the exact inverse of
# ModuleFrame.get_end_frame's (edge_class, parity) -> ModuleEdge mapping.
_ME_TO_CLASS_PARITY = {}
for _cls, (_e1, _e2) in EDGE_CLASS_TO_MODULE_EDGES.items():
    _ME_TO_CLASS_PARITY[int(_e1)] = (_cls, 0)
    _ME_TO_CLASS_PARITY[int(_e2)] = (_cls, 1)


def all_edges(levels, per_row):
    """Every physical edge (EdgeRef) of a levels x per_row lattice, exactly
    once. Built by directly inverting get_end_frame's own (edge_class, tile.x
    parity) <-> ModuleEdge mapping, so it always matches exactly whatever
    module grid is actually built - no sweeping/guessing a hex coordinate
    range and filtering it down, which previously left both duplicates
    (edges shared by two neighboring hex cells getting visited from both
    sides) and gaps (edges only reachable from a hex outside the swept
    range) - a "4x9" build should be exactly 36*12=432 edges and now is."""
    edges = []
    for h in range(levels):
        for l in range(per_row):
            for me in range(12):
                cls, parity = _ME_TO_CLASS_PARITY[me]
                edges.append(TileRef(2 * l + parity, h).edge(cls))
    return edges


def connected_walk(edges):
    """Order `edges` into a path where each step shares a vertex with the
    last wherever possible (a real snake trail, not teleporting) - DFS over
    the graph's own vertex adjacency (EdgeRef.vertex_pair, see
    py/lib/graph.py), covering every edge exactly once. Only jumps to a
    non-adjacent edge when a branch is fully explored and backtracking runs
    out (dead ends, or genuinely separate lattice pieces)."""
    vertex_edges, edge_vertices = {}, {}
    for er in edges:
        vp = EdgeRef.vertex_pair(er)
        vertex_edges.setdefault(vp.top, []).append(er)
        vertex_edges.setdefault(vp.bottom, []).append(er)
        edge_vertices[er] = (vp.top, vp.bottom)

    remaining = set(edges)
    order = []
    for start in edges:
        if start not in remaining:
            continue
        stack = [start]
        while stack:
            cur = stack.pop()
            if cur not in remaining:
                continue
            remaining.discard(cur)
            order.append(cur)
            v1, v2 = edge_vertices[cur]
            neighbors = [e for e in vertex_edges[v1] + vertex_edges[v2] if e in remaining]
            stack.extend(reversed(neighbors))            # DFS: explore nearest neighbors first
    return order


def build_path(levels, per_row):
    edges = all_edges(levels, per_row)
    path = connected_walk(edges)
    touched = {(er.tile.y, er.tile.x // 2) for er in path}
    return path, touched


def resolve_shape():
    shape = fetch_lattice_shape()
    if shape:
        return shape["levels"], shape["perRow"], True
    return DEFAULT_LEVELS, DEFAULT_PER_ROW, False


def main() -> None:
    client = LatticeClient()      # socket path from HINGE_SOCK / default

    levels, per_row, live = resolve_shape()
    path, touched = build_path(levels, per_row)
    source = "viewer" if live else "default (viewer not reachable yet)"
    print(f"brightness_cycle snake: {levels}x{per_row} modules ({source}), "
          f"{len(path)}-edge path across {len(touched)} modules, {SNAKE_LEN} edges long @ {FPS}fps")

    fader = ColorFader(VERY_BLUE, VERY_GREEN, FADE_FROM)
    snake = []          # [(edge_ref, col_a, col_b), ...] newest first, len <= SNAKE_LEN
    path_i = 0
    next_step = time.monotonic()
    next_shape_check = time.monotonic() + SHAPE_POLL_SECS

    try:
        while True:
            now = time.monotonic()

            if now >= next_shape_check:
                next_shape_check = now + SHAPE_POLL_SECS
                new_shape = fetch_lattice_shape()
                if new_shape and (new_shape["levels"], new_shape["perRow"]) != (levels, per_row):
                    levels, per_row = new_shape["levels"], new_shape["perRow"]
                    new_path, new_touched = build_path(levels, per_row)
                    for key in touched - new_touched:               # clear anything left behind
                        client.sendModule(f"{key[0]}-{key[1]}", ModuleFrame.blank())
                    path, touched = new_path, new_touched
                    snake, path_i = [], 0
                    print(f"brightness_cycle snake: rebuilt for {levels}x{per_row} modules, "
                          f"{len(path)}-edge path across {len(touched)} modules")

            fader.advance(RATE, HANDOFF_LEVEL, PAUSE_TICKS)
            col_a, col_b = fader.current_colors()

            if now >= next_step:
                next_step = now + STEP_SECS
                snake.insert(0, (path[path_i % len(path)], col_a, col_b))
                path_i += 1
                del snake[SNAKE_LEN:]

            buffers = {key: ModuleFrame.blank() for key in touched}
            for pos, (edge_ref, sa, sb) in enumerate(snake):
                mult = TAIL_BRIGHTNESS[pos]
                top_u = [c / 255 for c in lerp_color((0, 0, 0), sa, mult)]
                bot_u = [c / 255 for c in lerp_color((0, 0, 0), sb, mult)]

                mf = buffers[(edge_ref.tile.y, edge_ref.tile.x // 2)]
                top_end, bottom_end = EdgeRef.ends(edge_ref)
                top_frame = mf.get_end_frame(top_end)
                bottom_frame = mf.get_end_frame(bottom_end)
                for f in range(4):
                    top_frame[f][:] = top_u
                    bottom_frame[f][:] = bot_u

            for key, mf in buffers.items():
                h, l = key
                client.sendModule(l, h, mf)

            time.sleep(TICK)
    except KeyboardInterrupt:
        client.close()


if __name__ == "__main__":
    main()
