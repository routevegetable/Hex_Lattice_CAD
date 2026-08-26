from abc import ABC, abstractmethod
import abc
import asyncio
from collections import deque
from collections.abc import Callable, Iterable
import math
import random
import time
from typing import Any, Coroutine, Generator, Optional
from pylattice.frame import RGB, EndFrame, ModuleFrame
from pylattice.graph import EdgeClass, EdgeRef, Graph, TileRef, VertexClass, EndRef, VertexRef
from pylattice.lattice_client import LatticeClient
from pylattice.lattice_writer import LatticeWriter

from pylattice.examples.tempo import Event, EventLatch, History, periodic, psweep, sweep

ROWS = 2
COLS = 8

lattice = LatticeWriter(COLS, ROWS)

graph = Graph(COLS*2, ROWS)

def get_vertex_down_ends(v: VertexRef):
    return [end for end in graph.VERTEX[0,0].ends_cw() if end.top]

def randown(v: EndRef):
    return random.choice(get_vertex_down_ends(graph.VERTEX[1,2]))

v = graph.VERTEX[0,0]

vec = v.ends_cw()[0].physical_to_next()

def hsv(h: float, s: float, v: float) -> tuple[float,float,float]:
    h = (h % 1 + 1) % 1
    i = int(h * 6)
    f = h * 6 - i
    p, q, u = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    return [(v, u, p), (q, v, p), (p, v, u), (p, q, v), (u, p, v), (v, p, q)][i % 6]


# Want a latch per filament
# Actually want a function to take a latch and write it to the appropriate frame

ZERO = Event.for_now()


def make_filament_fn(end: EndRef, idx: int, offset: int) -> Callable[[Event[Any]],None]:
    latch: EventLatch[Any] = EventLatch()

    def filament_fn(now: Event[Any]):

        gate_prob = psweep(now, 800, 0.7, 0.0)
        gate_prob = gate_prob * gate_prob

        # Random trigger
        trg = latch.maybe(now, idx + end.__hash__(), 80, gate_prob)

        # Saturation envelope
        s = sweep(now, trg, 150, 0.6, 1)

        # Value envelope
        v = sweep(now, trg, 200, 1, 0, 0)

        # Color
        color = hsv(0.7, s, v)

        # This end
        lattice[end][idx] = [*color]

        # Other end
        lattice[end.other()][idx] = [*color]

    return filament_fn

filament_fns: list[Callable[[Event[Any]], None]] = []

# For each end, make a filament render function
for x in range(0, 8):
    for end in graph.HEX[x,1].ends():
        for i in range(0,4):
            filament_fns.append(make_filament_fn(end, i, offset=1000 if (x%2) == 0 else 0))


PETAL_PATH = "LRRRLRRLRRRLRR"

def draw_path(base: EndRef, path: str, idx: int, c: RGB):
    for end in base.path(path):
        for fr in [lattice[end], lattice[end.other()]]:
                fr[idx] = c


# For each edge, find the closest pole
# In the whole diagram, have a center point, and an angle to the 'equator'
# A pole is a quarter around the whole space from the center point, perpendicular to the equator
# Starting from tips the 3 vertexes out from a pole.
# Look at the vector from the pole to the current vertex
# Look at the 2 choices.
# Pick the one that's closest to that vector
# Repeat

# I guess the question we need to answer is, given an end/edge anywhere, what's the 'field line' going through it
# For that end/edge, find the nearest pole
# Draw a line from the end/edge to that pole
# That's the field line.
# Can control the brightness based on dot product

def vec_add(a: tuple[float,float], b: tuple[float,float]) -> tuple[float,float]:
    ax,ay = a
    bx,by = b
    return (ax+bx), (ay+by)

def vec_neg(a: tuple[float,float]) -> tuple[float,float]:
    ax,ay = a
    return (-ax), (-ay)

def vec_sub(a: tuple[float,float], b: tuple[float,float]) -> tuple[float,float]:
    return vec_add(a, vec_neg(b))

def vec_len(a: tuple[float,float]) -> float:
    ax,ay = a
    return math.sqrt(ax*ax + ay*ay)

def vec_norm(a: tuple[float, float]) -> tuple[float, float]:
    ax,ay = a
    len = vec_len(a)
    if len == 0:
        return a
    return ax / len, ay / len

def vec_dot(a: tuple[float,float], b: tuple[float,float]) -> float:
    ax,ay = a
    bx,by = b
    return ax * bx + ay * by 

def vec_ccw(a: tuple[float, float]) -> tuple[float,float]:
    ax,ay = a
    return -ay, ax

def vec_mul(a: tuple[float,float], b: tuple[float,float]) -> tuple[float,float]:
    ax,ay = a
    bx,by = b
    return ax * bx, ay * by 

def vec_rot(a: tuple[float, float], cw: float) -> tuple[float,float]:
    ax,ay = a
    s = math.sin(cw)
    c = math.cos(cw)
    return (ax * c + ay * -s), (ax * s + ay * c)

FIELD_DOT_THRESHOLD = 0.7

def draw_field_line(pole: tuple[float, float], edge: EdgeRef):

    # Vector for this edge
    ends = edge.ends()
    v_a, v_b = [end.vertex().physical() for end in ends]
    a_to_b = vec_norm(vec_sub(v_b, v_a))

    # Vector from pole to an end of this edge
    pole_to_a = vec_norm(vec_sub(v_a, pole))

    # Dot product between those
    ab = vec_dot(pole_to_a, a_to_b)


    print(ends, ab)
    if ab > FIELD_DOT_THRESHOLD:
        # Pointing the same way
        close, far = ends
    elif ab < -FIELD_DOT_THRESHOLD:
        # Pointing the opposite way
        far, close = ends
        ab = -ab
    else:
        return
    
    #ab = ab*0.3
    ab = ab - FIELD_DOT_THRESHOLD
    
    
    for i in range(4):
        lattice[close][i] = [ab, 0, 0]
        lattice[far][i] = [0, ab, ab]


def light_end(end: EndRef, idx: int, color: list[float]):
    """
    Light up an end of a filament
    """
    lattice[end][idx] = color

def light_edge(edge: EdgeRef, idx: int, color: list[float]):
    """
    Light up an edge (both ends)
    """
    for end in edge.ends():
        light_end(end, idx, color)


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



def make_zap_edge(end: EndRef):

    # Per-filament latches
    latches: list[EventLatch] = []
    for _ in range(4):
        latches.append(EventLatch())

    def zap_fn(now: Event, level: float, hues: tuple[float, float]):

        for idx in range(4):

            # Random trigger
            trg = latches[idx].maybe(now, idx + end.__hash__(), 50, level)

            # Saturation envelope
            s = sweep(now, trg, 100, 0.6, 1)

            # Value envelope
            v = sweep(now, trg, 120, 1, 0, 0)

            if v > 0.1:
                # This end
                lattice[end][idx] = [*hsv(hues[0], s, v)]

                # Other end
                lattice[end.other()][idx] = [*hsv(hues[-1], s, v)]

    return zap_fn

# Make a zap edge thingy for each edge end
zaps: dict[EndRef, Callable[[Event, Event[tuple[float, float]]], None]] = {}
for end in graph.ends():
    zaps[end] = make_zap_edge(end)




booms = History(30)
new_boom = EventLatch()


# Fire particles - parameter is x coord
fires = History[float](10)
last_new_fire = EventLatch()

def get_fire_particle_pos(now: Event, ev: Event[float]) -> tuple[float, float]:
    y_pos = math.pow(sweep(now, ev, 2000, 0, ROWS), 2)

    # Distance to this vertex:
    return (ev.data, y_pos)



# Each vertex has a different color assigned such that no neighboring vertexes have the same

# Periodically, filaments appear which are one of those colors
# the vertex 
# When a vertex is 'active', it extends filaments out to neighbors
# the neighbors change color to that vertex's color

# If neighbors are all the same color, the vertex 'dies' somehow





# Flowing:
# * all edges are watery
# * some lower-saturation, more 'dead' color starts spreading across, vertex by vertex
# * An edge only 'flows/zaps' when its neighbors aren't frozen.
# * A vertex freezes, meaning all of its ends stop flowing. 
# * 'flow' means zapping against a background color. Zapping requires both sides to make full filaments
# * Once one vertex is dead, its ends become the dead color as a solid background.
# * The edges still zap, less frequently, with the alive color
# * maybe 'flow' edge is light blue background, with white zapping
# * flow by default. all light blue with white zapping
# * Vertex dies, its ends become the dark background, the connected edges zap half as much, still white.




# * Alternative: no alive/dead, just color mixing
# * vertexes are all color a
# * some become color b.
# * where an edge has an a on one side and b on the other, zaps and both colors converge by max/min with each other

# So we start with all vertexes having their own state
# Edge zap rate is calculated from color dissimilarity. zap is purely saturation-drop. Hue stays the same.
# Each cycle, a vertex may flip its color, an edge is assigned a target color


# Each cycle, a vertex's new color is a blend of neighboring colors.
# Each end will color-sweep from its vertex's old color to the new one.
# The amount of zap at any given time is dictated by how different the end colors are from each other.


# Per-vertex color array. Could do something other than RGB next.
VertexColorMap = dict[VertexRef, RGB]
INIT_SPREAD_COLOR = [0,0,0]

def make_color_map() -> VertexColorMap:
    return {v: INIT_SPREAD_COLOR for v in graph.vertexes()}

spread_cycle_start = EventLatch()
spread_cycle_start.put()
current_vertex_colors: VertexColorMap = make_color_map()

def get_new_vertex_color(v: VertexRef) -> RGB:
    
    # Get neighbor vertexes
    neighbors = [end.other().vertex() for end in v.ends_cw()]
    neighbor_colors = [current_vertex_colors[v] for v in neighbors if v in current_vertex_colors]

    # Blend them

    #print(list(zip(*neighbor_colors)))
    blend_fn = max
    result = [blend_fn(*l) if len(l) > 1 else l[0] for l in zip(*neighbor_colors)]
    #print(list(zip(*neighbor_colors)), result)

    # Find the color that's dominant
    smallest = min(*result)

    for i in range(3):
        result[i] = result[i] * 0.3
        #if result[i] == smallest:
        #    result[i] = 0
    return result


# Given a pair of colors
def get_edge_zap_level(a: RGB, b: RGB) -> float:
    dr = (a[0] - b[0])
    dg = (a[1] - b[1])
    db = (a[2] - b[2])

    total = dr + dg + db

    # max possible is '3'
    return total / 3
    
    if a[0] + b[0] + a[1] + b[1] + a[2] + b[2]:
        pass

    dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

    # Max dot product is if all are different



    

SPREAD_CYCLE_LEN = 100

def spread_it(now: Event):
    global current_vertex_colors
    
    last_cycle = spread_cycle_start.read()
    current_cycle = spread_cycle_start.latch(periodic(now, SPREAD_CYCLE_LEN))
    latched_new = current_cycle.after(last_cycle)

    # Calculate new vertex colors by blending neighbors
    new_vertex_colors = {v: get_new_vertex_color(v) for v in current_vertex_colors}

    LOCK_THRESHOLD = 0.3
    # Sweep vertex edges from old to new colors
    temp_colors: VertexColorMap = {}
    for v in current_vertex_colors:
        old = current_vertex_colors[v]
        new = new_vertex_colors[v]

        #temp_colors[v] = old
        #continue

        if abs(old[0] - new[0]) < LOCK_THRESHOLD and abs(old[1] - new[1]) < LOCK_THRESHOLD and abs(old[2] - new[2]) < LOCK_THRESHOLD:
            temp_colors[v] = old
            continue


        #print(old, new)
        r = sweep(now, current_cycle, SPREAD_CYCLE_LEN, old[0], new[0])
        g = sweep(now, current_cycle, SPREAD_CYCLE_LEN, old[1], new[1])
        b = sweep(now, current_cycle, SPREAD_CYCLE_LEN, old[2], new[2])
        temp_colors[v] = [r,g,b]

    for v in temp_colors:
        for v_end in v.ends_cw():
            for i in range(4):
                lattice[v_end][i] = temp_colors[v]

    # Calculate per-edge zap level over the top
    for edge in graph.edges():
        end = edge.ends()[0]
        v1 = end.vertex()
        v2 = end.other().vertex()

        if v1 in temp_colors and v2 in temp_colors:
            level = get_edge_zap_level(temp_colors[v1], temp_colors[v2])
            zaps[end](now, level, (0.8, 0.8))
            #print(lattice[end][i])

    if latched_new:
        current_vertex_colors = new_vertex_colors

        # Randomize some colors
        for v in current_vertex_colors:
            rand = current_cycle.rand(v.__hash__())
            if rand % 100 == 0:
                h = current_cycle.rand(v.__hash__() + 1)
                current_vertex_colors[v] = hsv((h % 100) / 100, 1, 1)
    

# Over that cycle, the ends converge on the new color while zapping

# Next cycle, the color 

# * A vertex




# Each filament needs a latch associated with it that survives between frames

# Maybe it's up to a drawfn to allocate whatever resources it needs
# Annoying that allocation is a thing

# Every pas

# This pattern is good for where-first

# We could just consider the 



# Filamentfn is a 
# Can combine multiple filamentvalues
#

# Two ideas:
# * A filament's behavior is set to either: SOLID, RANDOM (period, probability), both with a top and bottommost color
# * CMYK
# * Starting with 1 color, new one begins to intrude, new on takes over
#


rains = [
    EventLatch(),
    EventLatch(),
    EventLatch(),
    EventLatch(),
]


FIRE_BASE_COUNT = 10
fire_bases: list[EventLatch] = []
for _ in range(FIRE_BASE_COUNT):
    fire_bases.append(EventLatch())


def line() -> Iterable[EndRef]:
    start = graph.TILE[1,1].top_end(EdgeClass.A)
    return start.path("LLRRL")





while True:
    lattice.clear()

    now = Event.for_now()

    for i,fb in enumerate(fire_bases):
        fb.maybe(now, i, 300, 0.3)


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




    if False:
        hex_ends = list(graph.HEX[1,0].ends())
        fire_ends = [hex_ends[0], hex_ends[-1].other()]
        for iBase, fb in enumerate(fire_bases):
            
            base = fire_ends[iBase % len(fire_ends)]

            fbe = fb.read()
            if fbe is None:
                continue

            if iBase % 2 == 0:
                fire_path(base, "RRL", fbe)
            else:
                fire_path(base, "LLR", fbe)


    if False:

        # Fire is a number of particles
        new_fire = periodic(now, 200)
        if new_fire.after(last_new_fire.read()):
            last_new_fire.latch(new_fire)
            new_fire = new_fire.with_data(new_fire.rand() % 16)
            fires.update().latch(new_fire)


        for vertex in graph.vertexes():

            vertex_pos = vertex.physical()

            for fire in fires.events():
                if fire is None:
                    continue
                fire_pos = get_fire_particle_pos(now, fire)

                # Distance from vertex to this particle
                dist = vec_len(vec_sub(fire_pos, vertex_pos))
                #print(dist)
                #if dist > 3:
                #    continue
                #print(fire_pos, 1/(1 + dist*20))

                for end in vertex.ends_cw():
                    for idx in range(4):
                        o_r,o_g,o_b = lattice[end][idx]
                        n_r,n_g, n_b = hsv(0.1, vertex_pos[1]/ROWS, 1/(1 + dist * FOCUS))
                        lattice[end][idx] = [max(o_r, n_r), max(o_g, n_g), max(o_b, n_b)]


    CLOUD = [1, 1, 1]

    DROP = [0, 0.3, 1]

    WATER = [0, 0, 1]



    RAIN_THRESHOLD = 0.6

    RAIN_FALL_TIME = 120

    for i in range(4):
        my_rain = rains[i]
        my_rain.maybe(now, i, 300, 0.25, i * 13)

    last_end: EndRef | None = None
    for dist, end in enumerate(line()):
        for i in range(4):
            my_rain = rains[i]

            delay = dist * RAIN_FALL_TIME
            
            if my_rain.read() is None:
                continue

            rads = sweep(now, my_rain.read().delay(delay), RAIN_FALL_TIME, 0, math.pi)
            brightness = math.sin(rads)

            if brightness < RAIN_THRESHOLD:
                brightness = 0

            drop_color = hsv(0.66, 1, brightness)
            lattice[end][i] = drop_color

            if last_end is not None:
                lattice[last_end.other()][i] = drop_color



            #light_edge(end, i, [0.2, 0.7, 1])
        last_end = end


    def vary(now: Event, start: float, end: float, period: int, offset: int) -> float:
        rads = psweep(now, period, 0, 2 * 3.141, offset)

        y = (math.sin(rads) / 2) + 0.5 # 0 to 1, starting at 0.5

        range = end - start

        output_offset = range * y
        return start + output_offset

    
    FLOW_PERIOD = 1500
    for i in range(4):
        
        hue = vary(now, 0.60, 0.66, FLOW_PERIOD, i * FLOW_PERIOD/4)
        hue2 = vary(now, 0.60, 0.66, FLOW_PERIOD, (i + 2) * FLOW_PERIOD/4)

        lattice[end][i] = hsv(hue, 1, 0.2)
        lattice[end.other()][i] = hsv(hue2, 1, 0.2)
    

    all = list(line())

    CLOUD_HUES = [0.05, 0.98, 0.66]

    for n, end in enumerate([all[0], all[0].other(), all[1]]):

        for i in range(4):
            offset = (n + i)
            
            v = vary(now, 1, 0, FLOW_PERIOD, offset * FLOW_PERIOD/4)
            hue = CLOUD_HUES[offset % 3]

            lattice[end][i] = hsv(hue, 0.4, v)

    #zaps[end](now, 1, (2/3,2/3))

    #spread_it(now)

    TRANS_COLORS = [
        [0.2, 0.7, 1],
        [1, 0.45, 0.55],
        [1, 1, 1]
    ]

    CYCLE_LEN = 1000
    cycle = periodic(now, CYCLE_LEN)


    if False:
        # Do triangle
        last_end = None
        for i, end in enumerate(graph.HEX[0,0].ends()):
            if i % 2 == 0:
                color_offset = i // 2
                color_idx = int(color_offset + psweep(now, CYCLE_LEN, 0, 3))

                from_color = TRANS_COLORS[color_idx % 3]
                to_color = TRANS_COLORS[(color_idx + 1) % 3]

                for j in range(4):
                    lattice[end][j] = from_color
                    lattice[end.other()][j] = to_color
            else:
                p = cycle.delay((i // 2) * CYCLE_LEN / 3)
                level = sweep(now, p, CYCLE_LEN*0.6, 0.7, 0.00, 0.00)
                hue = p.rand(0) % 100 / 100
                zaps[end](now, level, (hue, hue))



    if False:
        fire_boom = periodic(now, 300)
        if fire_boom.after(new_boom.read()):
            new_boom.latch(fire_boom)
            booms.update().latch(fire_boom)
        
        for be in booms.events():
            if be is None:
                continue
            x = be.rand(0) % 3
            y = be.rand(1) % 3

            for end in graph.HEX[x,y].ends():
                level = sweep(now, be, 400, 0.7, 0.00, 0.00)
                zaps[end](now, level, (be.rand(0) % 100 / 100 , be.rand(1) % 100 / 100))

                for dist, path_end, ev in time_path(end, "LLR", be, 20):
                    if path_end in zaps:
                        level = sweep(now, ev, 800, 0.7, 0.00, 0.00)
                        #print(ev.rand(0))
                        #zaps[path_end](now, level, (ev.rand(0) % 100 / 100 , ev.rand(1) % 100 / 100))
        
    

    test_pole = (psweep(Event.for_now(), 8000, 0, 10),2)

    # All edges in the whole thing
    for end in graph.ends():
        #draw_field_line(test_pole, end)
        ...


    # Render filaments
    #for fn in filament_fns:s
    #    fn(Event.for_now())

    steps = math.floor(psweep(Event.for_now(), 1000, 0, 6))
    ypos = math.floor(psweep(Event.for_now(), 60000, 1, 30))
    pos = 1 + ypos // 2 # math.floor(psweep(Event.for_now(), 4000, 1, 14))

    petal_bases = enumerate(graph.HEX[pos,ypos].rotate(steps).ends())

    # Draw petals
    if False:
        for ib, base in petal_bases:
            if ib % 2 == 0:
                continue

            color = [
                [1,1,0],
                [1,0,1],
                [0,1,1]
            ][ib//2]

            filament = ib % 4

            #draw_path(base, PETAL_PATH, filament, color)
            draw_path(base, "RLRRRRLRR", filament, color)
        
        for f in range(4):
            draw_path(graph.HEX[pos,ypos].base, "RRRRR", f, [0.1,0.1,0.1])
            ...

    time.sleep(0.02)
    lattice.show()
    continue

    # Clockwise
    for v_end in graph.VERTEX[1,3].ends_cw():

        # Draw a 'line'
        for dist, end in enumerate(v_end.path("RRRLR")):

            # Light up both ends of each filament
            for j in range(0,4):
                lattice[end][j] = [255,0,0]
                
                other = end.other()
                lattice[other][j] = [0,0,255]

    if False:
            i = int(time.monotonic()*10) % 6
            for j, end in enumerate(graph.HEX[2,0].rotate(i).ends()):
                if j % 3 == 0:
                    continue
                lattice[end][0][j % 3] = 1

                other = end.other()
                lattice[other][2][j % 3] = 1

    #down = randown(current)
    # Down is a down-pointing end
    lattice.show()
    time.sleep(0.001)
    

# Send frames