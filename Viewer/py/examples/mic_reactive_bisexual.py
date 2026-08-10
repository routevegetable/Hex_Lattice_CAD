"""Example: port of the CircuitPython rig's mic_reactive() (program.py on the
board) to the lattice simulation, using the flat Pixels/sendChannels API (see
four_colors.py / color_temp_lightning_edges.py) rather than ModuleFrame/the
graph API.

WHAT THE RIG DID
-----------------
mic_reactive() lights a random subset of the hexagon's 8 pairs (PAIRS in
config.py) each frame, sized by the latest volume level read off a host-side
mic bridge over usb_cdc ("<volume>,<bass>,<treble>,<pitch0>,...\\n" lines,
one pitch value per edge - see mic_bridge.py). The stock version only ever
looks at the volume field and picks each lit pair's color at random from a
small fixed palette (MIC_SCHEME_WHITE/RED_BLUE_PURP/etc, colors.py).

THIS PORT - RESPONDING TO VOLUME *AND* PITCH
-----------------------------------------------
Color here is spatial, not time-driven: each edge gets a fixed spot on
bisexual_edges_gradient() (colors.py's straight blue -> purple -> pink
sweep, built exactly for this - one fixed edge reads strong blue, the
opposite edge reads strong pink, everything between blends smoothly through
purple) and stays there for the life of the process, the same way
color_temp_lightning_edges positions edges on its red->blue gradient by
angular distance from a fixed `blue_edge`. Nothing about the hue cycles
over time or with the audio.
Volume and pitch instead drive brightness/how much of each edge lights up,
the same floor/gamma shaping the stock rig functions use: each edge's own
pitch band (from mic_reactive_pitch_edges' per-edge split) sets how much of
that edge's lit-pair budget is used, gated by the overall volume level (see
mic_reactive_bisexual() below) - so a pitch band only lights its edge when
there's also enough volume overall, and the spatial blue/purple/pink map
just shows through wherever the audio currently lights up.
On top of that, an especially loud moment (overall volume crossing
flash_threshold) triggers a brief orange-or-white flash across every pixel
on the hexagon - instant on, exponential decay (flash_decay_secs) - blended
on top of whatever the pitch/gradient look is currently showing, gated by
flash_cooldown_secs so one loud passage flashes once instead of re-lighting
every frame it stays loud.

TRANSLATING TO THIS MODULE'S API - CONCERNS
---------------------------------------------
1. Pixels/sendChannels bypasses ModuleFrame entirely - same as four_colors.py
   / color_temp_lightning_edges.py, this writes 48 raw (r, g, b) ints into
   channel 0 and ships them with sendChannels, rather than going through
   ModuleFrame.serialize's 4-channel/CHANNEL_EDGES layout. See concern #1 in
   color_temp_lightning_edges.py's docstring for the full explanation of why
   that means this won't visually decode in the lite viewer today.
2. Real mic input, no board/serial hop needed. The rig's _MicLine reads a
   live host-side mic bridge (apps/hexes/mic_bridge.py) over usb_cdc, a
   serial port that only exists because the board is a separate microcontroller
   from the machine running the mic. This script and the mic are on the same
   machine already (it's driving the lattice sim over sendChannels, not a
   board), so LiveMicLine below does mic_bridge.py's exact capture/FFT/
   banding in-process instead - same volume/bass/treble math, and NUM_EDGES
   (not mic_bridge.py's hardcoded 5) log-spaced pitch bands, handed straight
   to mic_reactive_bisexual() as `mic_line`. Needs `pip install sounddevice
   numpy`; main() falls back to FakeMicLine (a straight port of the rig's
   own no-mic stand-in: a slowly wandering ambient level with occasional
   sharp hit transients, each hit rerolling which pitch band is momentarily
   "dominant") if those aren't installed or no input device is found.
3. One hexagon, one location - see concern #2 in color_temp_lightning_edges.
   py's docstring; same MODULE_X/MODULE_Y single-location limitation here.
4. _sample_indices simplifies to random.sample() - the rig's version does a
   partial Fisher-Yates shuffle only because CircuitPython's random module
   has no random.sample(); host Python does, so this just calls it directly.
   Same "k distinct indices out of range(n)" result either way.
5. Fast frame rate. FPS below defaults to 120 (vs. 60 elsewhere in this
   directory) since a snappier refresh reads noticeably better for
   volume/pitch-reactive flicker than for the slower lightning/color-temp
   looks - raise/lower it if the UDP send rate becomes a bottleneck.

    1. python3 serve.py                 # creates the socket + serves the viewer
    2. python3 py/examples/mic_reactive_bisexual.py

Env: HINGE_SOCK overrides the socket path (LatticeClient resolves it).
"""
import math
import os
import random
import sys
import threading
import time

# Make the repo root importable so `py.lib` resolves.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from py.lib import LatticeClient   # noqa: E402

try:
    import numpy as np
    import sounddevice as sd
    _HAS_AUDIO = True
except ImportError:
    _HAS_AUDIO = False

MODULE_X = 0      # target module location (lateral)
MODULE_Y = 0      # target module location (height)
FPS = 120         # fast refresh - see concern #5 in the module docstring

# ---- ported from the rig's config.py ---------------------------------------
PAIRS = [[0, 5], [1, 4], [2, 7], [3, 6]]
NUM_EDGES = 6
PIXELS_PER_EDGE = len(PAIRS) * 2   # 8


# ---- same Pixels/PixelPairs wrappers as color_temp_lightning_edges.py: a
# channel-0 pixel buffer with show() to push it over sendChannels, addressed
# via (pair_ix, side, edge) like the rig's animation.py PixelPairs ----------
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
    a raw neopixel strip.
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


# ---- ported from the rig's colors.py: bisexual_gradient() and its helpers -
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


# straight blue -> purple -> pink, monotonic - built for a fixed positional mapping
# (fraction 0 = one fixed edge, fraction 1 = the edge directly opposite) rather than a
# traveling sweep, so there's no "returning" to loop back through: fraction 0 (blue_edge)
# reads strong blue, fraction 1 (the opposite edge) reads strong pink, with purple as the
# natural blend at the halfway point and two extra stops on either side of it for a
# smoother ramp in and out of purple rather than one long straight run each way.
# NOTE: this intentionally does NOT reuse the board's own colors.py BISEXUAL_EDGES_SEQ -
# that one's docstring claims the same "fraction 0 blue, fraction 1 pink, monotonic" shape,
# but its actual data points strong blue at fraction 0.6 (not 0) and pink-ish tones at BOTH
# ends, so it doesn't match its own description. Rebuilt cleanly here instead of porting
# that inconsistency forward. Green held at 0 across every stop, same reasoning as the
# original: even a little of it flattened purple into a duller mauve instead of a vivid violet.
BISEXUAL_EDGES_SEQ = [
    (0.0, (10, 0, 255)),     # strong blue
    (0.25, (95, 0, 210)),    # blue-purple blend
    (0.5, (180, 0, 180)),    # purple - the halfway blend
    (0.75, (230, 0, 165)),   # purple-pink blend
    (1.0, (255, 0, 150)),    # strong pink
]


def bisexual_edges_gradient(fraction: float):
    return interp_points(BISEXUAL_EDGES_SEQ, fraction)


# flash colors for "especially loud" moments - see flash_colors on mic_reactive_bisexual
FLASH_ORANGE = (255, 50, 0)
FLASH_WHITE = (255, 255, 255)


def _jitter_color(col, amount):
    return tuple(max(0, min(255, c + random.randint(-amount, amount))) for c in col)


def _lerp_color(a, b, t):
    return tuple(int(ac + (bc - ac) * t) for ac, bc in zip(a, b))


def _sample_indices(n, k):
    return random.sample(range(n), max(0, min(k, n)))


# ---- ported from the rig's program.py: FakeMicLine, a drop-in stand-in for
# the live usb_cdc mic bridge, used here since this simulation has no serial
# mic input of its own (see concern #2 in the module docstring) ------------
class FakeMicLine:
    """poll() -> "<volume>,<bass>,<treble>,<pitch0>,...,<pitch{NUM_EDGES-1}>\\n"
    (encoded bytes), same shape mic_bridge.py's real output has. Models a
    slowly wandering "ambient" level with occasional sharp hit transients -
    fast attack, exponential decay - each hit also rerolling which pitch
    band is momentarily "dominant" (neighboring bands get a fading share),
    so a downstream mic_reactive_bisexual reads as different edges lighting
    up on each hit rather than the same one every time.
    """

    def __init__(self, hit_chance_per_sec=0.7, decay_secs=0.35):
        self.level = 0.15
        self.target = 0.15
        self.hit = 0.0
        self.hit_chance_per_sec = hit_chance_per_sec
        self.decay_secs = decay_secs
        self.dominant = random.uniform(0, max(0, NUM_EDGES - 1))
        self.last_poll = time.monotonic()

    def poll(self):
        now = time.monotonic()
        dt = max(0.0, min(0.2, now - self.last_poll))
        self.last_poll = now

        self.target = max(0.05, min(0.35, self.target + random.uniform(-0.015, 0.015)))
        self.level += (self.target - self.level) * min(1.0, dt * 2)

        if random.random() < self.hit_chance_per_sec * dt:
            self.hit = random.uniform(0.4, 1.0)
            if NUM_EDGES > 1:
                self.dominant = random.uniform(0, NUM_EDGES - 1)
        else:
            self.hit *= math.exp(-dt / self.decay_secs)

        volume = max(0.0, min(1.0, self.level + self.hit + random.uniform(-0.02, 0.02)))
        bass = max(
            0.0,
            min(1.0, self.level * 0.9 + self.hit * random.uniform(0.7, 1.1) + random.uniform(-0.03, 0.03)),
        )
        treble = max(
            0.0,
            min(1.0, self.level * 0.6 + self.hit * random.uniform(0.1, 0.6) + random.uniform(-0.03, 0.03)),
        )

        pitch = []
        for i in range(NUM_EDGES):
            dist = abs(i - self.dominant)
            weight = math.exp(-dist * dist / 2.0)
            pitch.append(
                max(0.0, min(1.0, self.level * 0.3 * weight + self.hit * weight + random.uniform(0, 0.02)))
            )

        parts = [f"{volume:.3f}", f"{bass:.3f}", f"{treble:.3f}"] + [f"{p:.3f}" for p in pitch]
        return ",".join(parts).encode()


class LiveMicLine:
    """poll()-compatible real mic input - same shape as FakeMicLine's output,
    but from an actual microphone instead of synthesized. Ports mic_bridge.py's
    capture/FFT/banding straight into this process (see concern #2 in the
    module docstring for why no serial/board hop is needed here): a
    sounddevice.InputStream callback computes RMS volume, bass/treble band
    energy, and NUM_EDGES log-spaced pitch-band energies every BLOCK_SIZE-
    sample block, each smoothed (SMOOTHING) the same way mic_bridge.py's did,
    and poll() just hands back the latest computed line - no actual line
    parsing/serialization round-trip, just matching the format for drop-in
    compatibility with FakeMicLine/mic_reactive_bisexual.

    Same floor/scale constants as mic_bridge.py for volume/bass/treble.
    mic_bridge.py's PITCH_FLOORS/PITCH_SCALES were hand-tuned per band for
    its hardcoded 5 bands specifically, and vary a lot band to band (floors
    300-1000, scales 1800-25000 - a real spectrum just doesn't carry the same
    energy at every frequency). Those don't line up 1:1 with NUM_EDGES (6)
    bands here, so __init__ below resamples mic_bridge.py's actual tuned
    floor/scale curve (in log-frequency space) onto our band centers instead
    of guessing one flat number for every band - a flat guess systematically
    under-reads whichever bands' real required scale is higher than the
    guess (they'd need more energy than they ever produce to register),
    which is exactly what "picking up less than the board did" looks like.
    """

    SAMPLE_RATE = 16000
    BLOCK_SIZE = 1024
    NOISE_FLOOR = 60
    FULL_SCALE = 3000
    SMOOTHING = 0.3
    BASS_RANGE_HZ = (20, 2000)
    TREBLE_RANGE_HZ = (4000, 8000)
    BASS_FLOOR, BASS_SCALE = 2000, 40000
    TREBLE_FLOOR, TREBLE_SCALE = 200, 12000
    PITCH_RANGE_HZ = (80, 8000)

    # mic_bridge.py's own hand-tuned 5-band floors/scales (see its NUM_PITCH_BANDS/
    # PITCH_FLOORS/PITCH_SCALES) - resampled onto NUM_EDGES bands in __init__ below
    # rather than reused as-is, since NUM_EDGES (6) != 5.
    _MIC_BRIDGE_NUM_PITCH_BANDS = 5
    _MIC_BRIDGE_PITCH_FLOORS = [500, 800, 1000, 700, 300]
    _MIC_BRIDGE_PITCH_SCALES = [6000, 7000, 25000, 3500, 1800]

    def __init__(self, device=None):
        if not _HAS_AUDIO:
            raise RuntimeError(
                "LiveMicLine needs sounddevice + numpy - pip install sounddevice numpy "
                "(or pass mic_line=FakeMicLine() instead)"
            )
        self._window = np.hanning(self.BLOCK_SIZE)
        freqs = np.fft.rfftfreq(self.BLOCK_SIZE, 1 / self.SAMPLE_RATE)
        self._bass_bins = (freqs >= self.BASS_RANGE_HZ[0]) & (freqs <= self.BASS_RANGE_HZ[1])
        self._treble_bins = (freqs >= self.TREBLE_RANGE_HZ[0]) & (freqs <= self.TREBLE_RANGE_HZ[1])
        edges_hz = np.geomspace(self.PITCH_RANGE_HZ[0], self.PITCH_RANGE_HZ[1], NUM_EDGES + 1)
        self._pitch_bins = [
            (freqs >= edges_hz[i]) & (freqs < edges_hz[i + 1]) for i in range(NUM_EDGES)
        ]

        # resample mic_bridge.py's real per-band tuning (band-center Hz -> floor/scale,
        # log-log interpolated) onto our band centers instead of one flat guess
        src_edges = np.geomspace(
            *self.PITCH_RANGE_HZ, self._MIC_BRIDGE_NUM_PITCH_BANDS + 1
        )
        src_centers = np.log(np.sqrt(src_edges[:-1] * src_edges[1:]))
        dst_centers = np.log(np.sqrt(edges_hz[:-1] * edges_hz[1:]))
        self._pitch_floors = np.interp(dst_centers, src_centers, self._MIC_BRIDGE_PITCH_FLOORS)
        self._pitch_scales = np.interp(dst_centers, src_centers, self._MIC_BRIDGE_PITCH_SCALES)

        self._state = {"volume": 0.0, "bass": 0.0, "treble": 0.0, "pitch": [0.0] * NUM_EDGES}
        self._lock = threading.Lock()
        self._latest = None

        self._stream = sd.InputStream(
            samplerate=self.SAMPLE_RATE,
            blocksize=self.BLOCK_SIZE,
            channels=1,
            dtype="int16",
            device=device,
            callback=self._callback,
        )
        self._stream.start()

    def _band_level(self, spectrum, bins, floor, scale):
        energy = spectrum[bins].mean() if bins.any() else 0.0
        return max(0.0, min(1.0, (energy - floor) / (scale - floor)))

    def _callback(self, indata, frames, time_info, status):
        samples = indata[:, 0].astype(np.float64)
        rms = float(np.sqrt(np.mean(samples**2)))
        level = max(0.0, min(1.0, (rms - self.NOISE_FLOOR) / (self.FULL_SCALE - self.NOISE_FLOOR)))

        spectrum = np.abs(np.fft.rfft(samples * self._window))
        bass_level = self._band_level(spectrum, self._bass_bins, self.BASS_FLOOR, self.BASS_SCALE)
        treble_level = self._band_level(
            spectrum, self._treble_bins, self.TREBLE_FLOOR, self.TREBLE_SCALE
        )
        pitch_levels = [
            self._band_level(spectrum, bins, self._pitch_floors[i], self._pitch_scales[i])
            for i, bins in enumerate(self._pitch_bins)
        ]

        with self._lock:
            s = self._state
            s["volume"] += self.SMOOTHING * (level - s["volume"])
            s["bass"] += self.SMOOTHING * (bass_level - s["bass"])
            s["treble"] += self.SMOOTHING * (treble_level - s["treble"])
            for i, p in enumerate(pitch_levels):
                s["pitch"][i] += self.SMOOTHING * (p - s["pitch"][i])
            parts = [f"{s['volume']:.3f}", f"{s['bass']:.3f}", f"{s['treble']:.3f}"] + [
                f"{p:.3f}" for p in s["pitch"]
            ]
            self._latest = ",".join(parts).encode()

    def poll(self):
        with self._lock:
            return self._latest

    def close(self):
        self._stream.stop()
        self._stream.close()


def mic_reactive_bisexual(
    pixel_pairs,
    mic_line=None,
    gradient=bisexual_edges_gradient,
    blue_edge=0,
    max_pairs=len(PAIRS),
    gamma=3,
    floor=0.08,
    color_jitter=20,
    flash_colors=(FLASH_ORANGE, FLASH_WHITE),
    flash_threshold=0.85,
    flash_decay_secs=0.15,
    flash_cooldown_secs=0.3,
):
    """Build the per-tick frame() for the hexagon. TUNABLE PARAMETERS:

    pixel_pairs: a PixelPairs wrapping a Pixels buffer.
    mic_line: anything with a poll() returning the rig's
        "<volume>,<bass>,<treble>,<pitch0>,...\\n" line format (bytes) or
        None, same as the last-known-good line - see _MicLine/FakeMicLine.
        None (default) builds a FakeMicLine() (see concern #2 above).
    gradient: fraction (0-1) -> RGB, positioned by edge (not time/audio) -
        see edge_fraction below. Defaults to bisexual_edges_gradient.
    blue_edge: which edge (0-5) sits at fraction 0 / strong blue. The
        opposite edge (3 steps away on this 6-edge hexagon) lands at
        fraction 1 / strong pink; the rest fall in between by angular
        distance, same edge_fraction shape color_temp_lightning_edges uses
        for its red->blue gradient.
    max_pairs: how many of an edge's len(PAIRS) pairs can be lit at once
        when that edge's pitch band is at full strength *and* overall volume
        is loud - scales down from there with floor/gamma shaping.
    gamma / floor: shaping applied twice - once to the overall volume (a
        global gate: quiet audio dims/mutes every edge regardless of pitch)
        and once to each edge's own pitch-band level (which edge's lit-pair
        budget actually gets used). floor is the deadzone each is measured
        above; gamma shapes what's left (higher = louder/more-present-only
        needed for full effect).
    color_jitter: +/- per-channel color jitter (see _jitter_color) applied
        on top of each edge's fixed gradient color, for shade variation.
    flash_colors: tuple of (r, g, b) colors an "especially loud" moment can
        flash - default is one orange, one white; each trigger rolls a
        fresh random pick, same rand.choice-per-crackle idiom the rig's own
        flicker_color handling uses.
    flash_threshold: 0-1 overall volume level that counts as "especially
        loud" - a fresh crossing (gated by flash_cooldown_secs, not held
        volume) triggers a flash across every pixel on the hexagon, on top
        of whatever the pitch/gradient look is currently showing.
    flash_decay_secs: how fast a triggered flash fades back out - fast
        attack (instant, on trigger), exponential decay over roughly this
        many seconds, same shape as FakeMicLine/LightningStrikes' "hit".
    flash_cooldown_secs: minimum real time between flash triggers, so a
        sustained loud passage flashes once and decays rather than
        re-triggering (and re-picking a color) every single frame it stays
        above flash_threshold.
    """
    if mic_line is None:
        mic_line = FakeMicLine()

    state = {
        "volume": 0.0,
        "pitch": [0.0] * NUM_EDGES,
        "flash_level": 0.0,
        "flash_color": FLASH_WHITE,
        "last_flash": -1e9,
        "last_t": time.monotonic(),
    }

    half = NUM_EDGES / 2

    def edge_fraction(edge):
        delta = abs(edge - blue_edge) % NUM_EDGES
        angular_dist = min(delta, NUM_EDGES - delta)
        return angular_dist / half

    edge_colors = [gradient(edge_fraction(edge)) for edge in range(NUM_EDGES)]

    def frame():
        now = time.monotonic()
        dt = max(0.0, now - state["last_t"])
        state["last_t"] = now

        line = mic_line.poll()
        if line:
            parts = line.split(b",")
            try:
                state["volume"] = max(0.0, min(1.0, float(parts[0])))
                for i, p in enumerate(parts[3 : 3 + NUM_EDGES]):
                    state["pitch"][i] = max(0.0, min(1.0, float(p)))
            except ValueError:
                pass

        if (
            state["volume"] >= flash_threshold
            and now - state["last_flash"] >= flash_cooldown_secs
        ):
            state["flash_level"] = 1.0
            state["flash_color"] = random.choice(flash_colors)
            state["last_flash"] = now
        else:
            state["flash_level"] *= math.exp(-dt / flash_decay_secs)

        vol_lifted = max(0.0, (state["volume"] - floor) / (1 - floor))
        vol_shaped = vol_lifted**gamma

        for edge in range(NUM_EDGES):
            band_lifted = max(0.0, (state["pitch"][edge] - floor) / (1 - floor))
            band_shaped = band_lifted**gamma
            brightness = band_shaped * vol_shaped

            base_col = edge_colors[edge]
            num_lit = round(brightness * max_pairs)
            lit = set(_sample_indices(len(PAIRS), num_lit))

            for i in range(len(PAIRS)):
                if i in lit:
                    col = tuple(
                        int(c * brightness) for c in _jitter_color(base_col, color_jitter)
                    )
                else:
                    col = (0, 0, 0)
                if state["flash_level"] > 0.003:
                    col = _lerp_color(col, state["flash_color"], state["flash_level"])
                pixel_pairs.set(i, col, edge=edge)

    return frame


def main() -> None:
    client = LatticeClient()      # socket path from HINGE_SOCK / default
    pixels = Pixels(client, NUM_EDGES * PIXELS_PER_EDGE)
    pixel_pairs = PixelPairs(pixels)

    mic_line = None
    if _HAS_AUDIO:
        try:
            mic_line = LiveMicLine()
            print("mic_reactive_bisexual: using LiveMicLine (real mic input)")
        except Exception as exc:   # e.g. no input device available
            print(f"mic_reactive_bisexual: LiveMicLine unavailable ({exc}), falling back to FakeMicLine")
    else:
        print("mic_reactive_bisexual: sounddevice/numpy not installed, using FakeMicLine "
              "(pip install sounddevice numpy for real mic input)")

    frame = mic_reactive_bisexual(pixel_pairs, mic_line=mic_line)

    try:
        while True:
            frame()
            client.sendChannels(0, 0, [pixels._data, [], [], []])
            time.sleep(1 / FPS)
    except KeyboardInterrupt:
        if isinstance(mic_line, LiveMicLine):
            mic_line.close()
        client.close()


if __name__ == "__main__":
    main()
