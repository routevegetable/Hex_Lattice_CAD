"""Random flashes: each fiber ignites on its own schedule and flickers out."""

from pylattice.examples.colors import hsv
from pylattice.examples.tempo import Event, EventLatch, sweep
from pylattice.fields.types import Slot
from pylattice.graph import EdgeRef, Graph
from pylattice.instrument.types import Effect
from pylattice.lattice_writer import LatticeWriter


class Sparks(Effect):
    """Every edge's 4 fibers independently self-trigger a flash - full
    brightness held briefly, then a linear fade - gated by `value` so a
    strobe pad switches the whole thing on and off. `prob` is literally the
    probability that something, somewhere on the whole rig, is lit at any
    given instant: 0.25 means a one-in-four chance. There are many
    independent rolls happening (every fiber, every end, every edge, every
    period) - solved by inverting "P(at least one of N rolls hits)" for the
    single-roll rate that makes the whole-rig probability come out to
    `prob`.

    The two ends of a fiber flicker on fully independent schedules rather
    than mirroring each other, so it reads as individual points sparking
    rather than whole edges lighting up - the twinkle comes from each end
    landing lit or dark on its own, not from a rule that only one ever is."""

    hue: Slot
    sat: Slot
    value: Slot
    prob: Slot

    HOLD_MS = 200  # full brightness for this long after a trigger
    DECAY_MS = 1500  # then a linear fade to 0 over this long
    PERIOD_MS = HOLD_MS + DECAY_MS

    TRIALS_PER_EDGE = 4 * 2  # fibers x ends, each an independent roll

    def __init__(self):
        super().__init__()
        self._latches: dict[tuple[EdgeRef, int, int], EventLatch] = {}
        self._total_trials: int | None = None

    def render(self, now: Event, lattice: LatticeWriter, graph: Graph):

        if self._total_trials is None:
            # Sized off the actual graph, so it tracks whatever COLS/ROWS
            # hardware.py is set to rather than a number baked in here.
            self._total_trials = sum(1 for _ in graph.edges()) * self.TRIALS_PER_EDGE

        for edge in graph.edges():
            end = edge.ends()[0]
            other = end.other()

            for fiber in range(4):
                # Each end of the fiber gets its own latch, salt and offset,
                # so they roll and flicker fully independently instead of
                # mirroring each other.
                for side, side_end in ((0, end), (1, other)):
                    latch = self._latches.setdefault((edge, fiber, side), EventLatch())

                    # periodic() quantizes to tick boundaries shared by every
                    # caller unless offset says otherwise - without this,
                    # every end/fiber would roll its dice at the same
                    # instant, and whatever fires would all fire together.
                    # Spreading the offset across the whole period staggers
                    # the ticks instead.
                    salt = edge.__hash__() + fiber * 2 + side
                    offset = salt % self.PERIOD_MS

                    prob = self.prob.get(now, side_end)
                    # Invert P(something lit anywhere) = 1 - (1-likelihood)**total_trials
                    # for the single-roll likelihood that makes the whole-rig
                    # probability come out to `prob`.
                    likelihood = 1 - (1 - prob) ** (1 / self._total_trials)
                    trg = latch.maybe(now, salt, self.PERIOD_MS, likelihood, offset)

                    if trg is None or not now.after(trg):
                        continue

                    elapsed = now.when - trg.when
                    b = (
                        1.0
                        if elapsed <= self.HOLD_MS
                        else sweep(now, trg.delay(self.HOLD_MS), self.DECAY_MS, 1, 0)
                    )

                    v = b * self.value.get(now, side_end)
                    if v <= 0.001:
                        continue

                    color = list(
                        hsv(self.hue.get(now, side_end), self.sat.get(now, side_end), v)
                    )
                    lattice[side_end][fiber] = color
