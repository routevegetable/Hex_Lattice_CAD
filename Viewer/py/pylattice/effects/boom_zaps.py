
from collections.abc import Iterable
import math
from typing import Callable
from py.pylattice.examples.colors import hsv
from py.pylattice.examples.instrument import ScalarField
from py.pylattice.examples.tempo import Event, EventLatch, History, periodic, sweep
from py.pylattice.graph import EndRef, Graph
from py.pylattice.lattice_writer import LatticeWriter



# Given a path, we want a way of triggering something along that path
def time_path(base: EndRef, seq: Iterable[str], ev: Event, speed: float) -> Iterable[tuple[int, EndRef, Event]]:
    """
    Make a path with a speed
    speed is how many segments per sec.
    Yields (distance, end, delayed event)
    """
    msec_per_segment = 1000 / speed
    for i, end in enumerate(base.path(seq)):
        yield i, end, ev.delay(int(i * msec_per_segment))
        

def make_zap_edge(end: EndRef, lattice: LatticeWriter):

    # Per-filament latches
    latches: list[EventLatch] = []
    for _ in range(4):
        latches.append(EventLatch())

    def zap_fn(now: Event, level: float, hues: tuple[float, float]):

        for idx in range(4):

            # Random trigger
            trg = latches[idx].maybe(now, idx + end.__hash__(), 50+idx, level)

            # Saturation envelope
            # s = sweep(now, trg, 100, 0.6, 1)
            s = sweep(now, trg, 50, 0, 1)

            # Value envelope
            v = sweep(now, trg, 70, 1, 0, 0)

            if v > 0.1:
                # This end
                lattice[end][idx] = [*hsv(hues[0], 0, v)]

                # Other end
                lattice[end.other()][idx] = [*hsv(hues[-1], 0, v)]

    return zap_fn

# Make a zap edge thingy for each edge end
zaps: dict[EndRef, Callable[[Event, float, tuple[float, float]], None]] = {}

def init_boom_zaps(graph_: Graph, lattice_: LatticeWriter):
    global graph
    global lattice
    graph = graph_
    lattice = lattice_
    for end in graph.ends():
        zaps[end] = make_zap_edge(end, lattice)

booms = History(30)
new_boom = EventLatch()

def prob_zaps(now: Event, prob_field: ScalarField):
    
    for edge in graph.edges():
        end = edge.ends()[0]
        v = end.vertex()
        prob = prob_field.get(now, v)
        if prob < 0.9:
            prob = 0
        prob = prob / 6
        zaps[end](now, prob, (0.8, 0.6))

def run_boom_zaps(now: Event):

    FOCUS = 30

    def blend_max(end: EndRef, idx: int, n: list[float]):
        o_r,o_g,o_b = lattice[end][idx]
        n_r,n_g, n_b = n 
        lattice[end][idx] = [max(o_r, n_r), max(o_g, n_g), max(o_b, n_b)]

    def fire_path(base: EndRef, path: Iterable[str], ev: Event):

        last_end: list[EndRef] = []
        for i, path_end in enumerate(base.path(path)):

            y_pos = math.pow(sweep(now, ev, 3000, 0, len(path)) + 2, 2) - 4
            if y_pos < 0.1:
                return

            dy = i - y_pos
            dist = math.sqrt(dy*dy)
            h = (ev.rand(end.__hash__()) % 100) / 100
            s = i/len(path)
            v = 1/(5 + dist * FOCUS)
            #if i == 1:
                #print(h, s, v)
            n = hsv(h, s, v)

            for vend in last_end + [path_end]:
                for idx in range(4):
                    blend_max(vend, idx, n)
            
            last_end = [path_end.other()]

    fire_boom = periodic(now, 1000)
    if fire_boom.after(new_boom.read()):
        new_boom.latch(fire_boom)
        booms.update().latch(fire_boom)
    
    for be in booms.events():
        if be is None:
            continue
        x = be.rand(0) % 5
        y = be.rand(1) % 10

        for end in graph.VERTEX[x,y].ends_cw():
            # level = sweep(now, be, 400, 0.7, 0.00, 0.00)
            # c1, c2 = .66, .69
            
            # # zaps[end](now, level, (be.rand(0) % 100 / 100 , be.rand(1) % 100 / 100))
            # zaps[end](now, level, (c1, c2))

            c3, c4 = .99, .05
            for dist, path_end, ev in time_path(end, "L", be, 20):
                if path_end in zaps:
                    level = sweep(now, ev, 800, 0.7, 0.00, 0.00)
                    # level = .1
                    #print(ev.rand(0))
                    # zaps[path_end](now, level, (ev.rand(0) % 100 / 100 , ev.rand(1) % 100 / 100))
                    zaps[path_end](now, level, (c3, c4))