"""The audio input: its spectrum, the playing patch's ranges judged on it, and
the operators that read each range."""

import math
from collections import deque
from typing import TYPE_CHECKING

import numpy as np
import sounddevice as sd

from pylattice.examples.midi import MIDI
from pylattice.examples.tempo import Event
from pylattice.fields.operators import Arity, Operator
from pylattice.fields.types import ScalarField
from pylattice.graph import EndRef

if TYPE_CHECKING:
    from pylattice.instrument.patch import FFTRange


class Spectrum:
    """The audio input's spectrum, taken once a frame.

    Levels and spectral flux are worked out at POINTS frequencies from LOW to
    HIGH, spaced geometrically, each over a band reaching halfway to its
    neighbours and never narrower than one bin. A level is the energy in its
    band, as an amplitude against full scale; flux is how far the band's log
    magnitude rose since the last spectrum, per bin. Neither is scaled here:
    each range resamples them into bins, and has one AGC for its levels and
    one for its flux, which its operators read the bins against.

    The main loop calls `listen` once a frame with the playing patch's ranges:
    it reads the input, judges each range, and holds each range's note on the
    MIDI it was given while that range is hit.
    """

    LOW = 20            # Hz at the first point
    HIGH = 16000        # Hz at the last

    WINDOW = 8192       # samples the spectrum is taken over
    POINTS = 256        # frequencies levels and flux are worked out at
    LOG_GAIN = 100      # flux is taken on log(1 + LOG_GAIN * magnitude)
    SHOWN_HALF_LIFE = 30    # ms a flux peak takes to halve in the flux shown
    AGC_HALF_LIFE = 500     # ms for a range's AGC level to fall to half
    LEVEL_FLOOR = 0.01      # the lowest a range's level AGC goes
    FLUX_FLOOR = 0.05       # the lowest a range's flux AGC goes

    def __init__(self, midi: MIDI):
        self._midi = midi
        self._beat_notes: set[int] = set()     # notes the ranges are holding

        # How wide each point's band is, in octaves: the space between points.
        self.width = math.log2(self.HIGH / self.LOW) / (self.POINTS - 1)

        self._stream = sd.InputStream(channels=1, dtype="float32")
        self._stream.start()

        self._samples = np.zeros(self.WINDOW, dtype=np.float32)
        self._window = np.hanning(self.WINDOW)

        # Each frequency in bins, and the cumulative sums' index for it: bin k
        # spans k - 0.5 to k + 0.5, so edge k + 1 sits at k + 0.5.
        self.per_bin = self._stream.samplerate / self.WINDOW
        self._centres = self.LOW * (self.HIGH / self.LOW) ** np.linspace(0, 1, self.POINTS) / self.per_bin
        self._edges = np.arange(self.WINDOW // 2 + 2)

        # Power and flux, each summed up the bins, and the log magnitudes the
        # next spectrum's flux is taken against.
        self._total = np.zeros(self.WINDOW // 2 + 2)
        self._flux_total = np.zeros(self.WINDOW // 2 + 2)
        self._log_mags = np.zeros(self.WINDOW // 2 + 1)

        self._levels = [0.0] * self.POINTS
        self._flux_shown = np.zeros(self.POINTS)
        self._flux = [0.0] * self.POINTS
        self._power_curve = (np.zeros(self.POINTS), np.zeros(self.POINTS))
        self._flux_curve = (np.zeros(self.POINTS), np.zeros(self.POINTS))
        self._heard: Event | None = None

        # The playing patch's ranges, and how each is being judged, in order.
        self.config: list[FFTRange] = []
        self.ranges: list[RangeState] = []
        self._judged: Event | None = None

    def range_level(self, index: int) -> "RangeOperator":
        """An operator reading the levels across the playing patch's range `index`."""
        return RangeOperator(self, index, flux=False)

    def range_flux(self, index: int) -> "RangeOperator":
        """An operator reading the flux across the playing patch's range `index`."""
        return RangeOperator(self, index, flux=True)

    def range_level_avg(self, index: int) -> "RangeAverage":
        """A field reading the mean level of the playing patch's range `index`."""
        return RangeAverage(self, index, flux=False)

    def range_flux_avg(self, index: int) -> "RangeAverage":
        """A field reading the mean flux of the playing patch's range `index`."""
        return RangeAverage(self, index, flux=True)

    def bins(self) -> list[float]:
        """The level at each frequency, LOW to HIGH."""
        return self._levels

    def fluxes(self) -> list[float]:
        """The flux at each frequency, LOW to HIGH, each the highest of the
        last SHOWN_HALF_LIFE or so."""
        return self._flux

    def place(self, hz: float) -> float:
        """Where a frequency falls, from LOW (0) to HIGH (1)."""
        return math.log(hz / self.LOW) / math.log(self.HIGH / self.LOW)

    def _spans(self, lo, hi):
        """Where each pair of frequencies, in bins, starts and ends on the
        cumulative sums, never narrower than one bin."""
        mid = (lo + hi) / 2 + 0.5
        span = np.maximum(hi - lo, 1) / 2
        return mid - span, mid + span

    def _bands(self, lo, hi):
        """The level between each pair of frequencies, in bins."""
        a, b = self._spans(lo, hi)
        return np.sqrt(np.interp(b, self._edges, self._total)
                       - np.interp(a, self._edges, self._total))

    def _fluxes(self, lo, hi):
        """The flux between each pair of frequencies, in bins, per bin."""
        a, b = self._spans(lo, hi)
        return (np.interp(b, self._edges, self._flux_total)
                - np.interp(a, self._edges, self._flux_total)) / (b - a)

    def listen(self, now: Event, ranges: "list[FFTRange]"):
        """Read the input, judge each range, and hold each range's note while
        it is hit."""
        self._read(now)
        self._judge(now, ranges)

        # A note two ranges share is held while either is hit.
        wanted: dict[int, bool] = {}
        for r, state in zip(ranges, self.ranges):
            if r.beat_note is not None:
                wanted[r.beat_note] = wanted.get(r.beat_note, False) or state.held

        for note in self._beat_notes - wanted.keys():
            self._midi.set_note(note, False)
        for note, held in wanted.items():
            self._midi.set_note(note, held)
        self._beat_notes = set(wanted)

    def _read(self, now: Event):
        """Take in whatever the input has, and work the levels and flux out afresh."""
        n = self._stream.read_available
        if n == 0:
            return

        block, _overflowed = self._stream.read(n)
        n = min(n, self.WINDOW)
        self._samples[:-n] = self._samples[n:]
        self._samples[-n:] = block[-n:, 0]

        x = self._samples - self._samples.mean()
        # A full-scale sine comes to 1: its peak bin is WINDOW / 4 through a
        # Hann window, and its power spreads 1, 1/4, 1/4 over three bins.
        mags = np.abs(np.fft.rfft(x * self._window)) / (self.WINDOW / 4)
        self._total = np.concatenate(([0.0], np.cumsum(mags * mags / 1.5)))

        log_mags = np.log1p(self.LOG_GAIN * mags)
        self._flux_total = np.concatenate(
            ([0.0], np.cumsum(np.maximum(log_mags - self._log_mags, 0))))
        self._log_mags = log_mags

        dt = now.when - self._heard.when if self._heard else 0
        self._heard = now

        half = 2 ** (self.width / 2)
        lo, hi = self._centres / half, self._centres * half
        levels = self._bands(lo, hi)
        self._levels = levels.tolist()

        flux = self._fluxes(lo, hi)
        self._flux_shown = np.maximum(flux, self._flux_shown * 0.5 ** (dt / self.SHOWN_HALF_LIFE))
        self._flux = self._flux_shown.tolist()

        # Running areas under the power and flux curves, point by point, for
        # averaging them over any stretch of the spectrum.
        self._power_curve = (levels * levels, _areas(levels * levels))
        self._flux_curve = (flux, _areas(flux))

    def _judge(self, now: Event, ranges: "list[FFTRange]"):
        """Judge each range afresh, one state per range in order, and work out
        the bins and AGC levels its operators read."""
        self.config = ranges
        del self.ranges[len(ranges):]
        self.ranges += [RangeState() for _ in range(len(ranges) - len(self.ranges))]

        dt = now.when - self._judged.when if self._judged else 0
        self._judged = now

        for state, r in zip(self.ranges, ranges):
            # The range's span of points, divided into its bins: the level of
            # each is the RMS across it, the flux the mean.
            edges = np.linspace(self.place(r.min_hz), self.place(r.max_hz),
                                r.bins + 1).clip(0, 1) * (self.POINTS - 1)
            levels = np.sqrt(_means(*self._power_curve, edges))
            fluxes = _means(*self._flux_curve, edges)

            # Beats are judged on the bins as heard: their mean flux, and the
            # RMS of their levels for how loud the band is.
            state.update(float(fluxes.mean()), float(np.sqrt((levels * levels).mean())), dt, r)

            # Then smoothed, if the range asks for it - afresh when it has
            # changed how many bins it has.
            if len(state.levels) != r.bins:
                state.levels, state.fluxes = levels, fluxes
            if r.smooth_ms > 0:
                follow = 1 - math.exp(-dt / r.smooth_ms)
                levels = state.levels + (levels - state.levels) * follow
                fluxes = state.fluxes + (fluxes - state.fluxes) * follow
            state.levels, state.fluxes = levels, fluxes

            state.level_bins = levels.tolist()
            state.flux_bins = fluxes.tolist()

            # One AGC level for the whole range, riding on the loudest of its
            # bins as its operators read them, and halving every AGC_HALF_LIFE
            # once they fall away.
            fall = 0.5 ** (dt / self.AGC_HALF_LIFE)
            state.level_agc = max(float(levels.max()), state.level_agc * fall, self.LEVEL_FLOOR)
            state.flux_agc = max(float(fluxes.max()), state.flux_agc * fall, self.FLUX_FLOOR)

            # The bins' means against the same AGC, for the range's averages.
            state.level_avg = float(levels.mean()) / state.level_agc
            state.flux_avg = float(fluxes.mean()) / state.flux_agc


def _areas(values):
    """The area under a curve through `values`, one per point, from the first
    point to each."""
    return np.concatenate(([0.0], np.cumsum((values[1:] + values[:-1]) / 2)))


def _means(values, areas, edges):
    """The curve through `values` averaged between each pair of neighbouring
    edges, which are points, fractions allowed."""
    i = np.minimum(edges.astype(int), len(values) - 2)
    f = edges - i
    under = areas[i] + values[i] * f + (values[i + 1] - values[i]) * f * f / 2
    return np.diff(under) / np.maximum(np.diff(edges), 1e-9)


class RangeState:
    """Whether one range has just been hit, judged on its spectral flux.

    The flux is smoothed with a time constant of SMOOTH, and the last
    agc_half_life_ms of the smoothed flux kept. The note goes down when the
    smoothed flux rises the range's `deviations` above that stretch's median - if the
    band is no quieter than FLOOR, and the last press was GAP ago or more - and
    comes up when it falls back below the median. A deviation is the median
    absolute deviation, scaled to match a standard deviation, so a few big hits
    move neither it nor the median much.
    """

    SMOOTH = 15         # ms, the flux's time constant
    FLOOR = 0.01        # the quietest band level, as an amplitude, that can press it
    GAP = 150           # ms between presses at the least
    MAD_SCALE = 1.4826  # median absolute deviation to standard deviation, for a normal spread

    def __init__(self):
        self.flux = 0.0         # smoothed
        self.median = 0.0
        self.deviation = 0.0
        self.held = False
        self.spread = 0.0       # deviations above the median that press the note, as last judged
        self.presses = 0        # how many times the note has gone down
        self._since = self.GAP  # ms since the note last went down

        # The smoothed flux of late, against a clock of this range's own.
        self._history: deque[tuple[int, float]] = deque()
        self._clock = 0

        # The range's level and flux in its bins, smoothed, and its AGC level
        # for each, which its operators read the bins against. Kept by the
        # Spectrum.
        self.levels = np.zeros(0)
        self.fluxes = np.zeros(0)
        self.level_bins: list[float] = []
        self.flux_bins: list[float] = []
        self.level_agc = Spectrum.LEVEL_FLOOR
        self.flux_agc = Spectrum.FLUX_FLOOR
        self.level_avg = 0.0
        self.flux_avg = 0.0

    def update(self, flux: float, energy: float, dt: int, r: "FFTRange"):
        self.spread = r.deviations
        self.flux += (flux - self.flux) * (1 - math.exp(-dt / self.SMOOTH))
        flux = self.flux

        self._clock += dt
        self._history.append((self._clock, flux))
        while self._history[0][0] <= self._clock - r.agc_half_life_ms:
            self._history.popleft()

        values = sorted(v for _, v in self._history)
        self.median = _median(values)
        self.deviation = self.MAD_SCALE * _median(sorted(abs(v - self.median) for v in values))

        self._since += dt

        if self.held:
            self.held = flux >= self.median
        else:
            self.held = (flux >= self.median + self.spread * self.deviation
                         and energy >= self.FLOOR and self._since >= self.GAP)
            if self.held:
                self._since = 0
                self.presses += 1


def _median(ordered: list[float]) -> float:
    """The median of a list already in order."""
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


class RangeOperator(Operator):
    """The levels, or the flux, across one of the playing patch's ranges, from
    its bins smoothed as the range says, against the range's AGC level - one
    for the whole range, so the bins keep their sizes against each other.

    The argument runs across the range, 0 its lowest frequency and 1 its
    highest, so `fft_0(v_gradient)` spreads range 0 up the lattice. Each bin's
    value sits at its centre, with straight lines between, and the end bins'
    values hold out to the range's edges. 0 when the patch has no such range.
    """

    arity = Arity.UNARY

    def __init__(self, spectrum: Spectrum, index: int, flux: bool):
        self._spectrum = spectrum
        self._index = index
        self._flux = flux

    def get(self, now: Event, end: EndRef, *args: ScalarField) -> float:
        s = self._spectrum
        if self._index >= len(s.config):
            return 0.0

        state = s.ranges[self._index]
        values, agc = ((state.flux_bins, state.flux_agc) if self._flux
                       else (state.level_bins, state.level_agc))

        # Where among the bin centres: centre k is at (k + 0.5) / bins.
        last = len(values) - 1
        at = min(max(args[0].get(now, end) * len(values) - 0.5, 0), last)
        i = min(int(at), last - 1)
        return (values[i] + (values[i + 1] - values[i]) * (at - i)) / agc


class RangeAverage(ScalarField):
    """The mean level, or the mean flux, of one of the playing patch's ranges
    over all its bins, against the range's AGC - the same everywhere, and 0
    when the patch has no such range."""

    def __init__(self, spectrum: Spectrum, index: int, flux: bool):
        self._spectrum = spectrum
        self._index = index
        self._flux = flux

    def get(self, now: Event, end: EndRef) -> float:
        ranges = self._spectrum.ranges
        if self._index >= len(ranges):
            return 0.0

        state = ranges[self._index]
        return state.flux_avg if self._flux else state.level_avg
