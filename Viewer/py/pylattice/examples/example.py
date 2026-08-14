import random
import time
from typing import Optional
from pylattice.frame import EndFrame, ModuleFrame
from pylattice.graph import HEX, VERTEX, TileRef, VertexClass, EndRef, VertexRef
from pylattice.lattice_client import LatticeClient
from pylattice.lattice_writer import LatticeWriter

ROWS = 4
COLS = 4

lattice = LatticeWriter(COLS, ROWS)


# Clockwise
for v_end in []: #VERTEX[1,2].ends_cw():

    # Draw a 'line'
    for dist, end in enumerate(v_end.path("RRRLRRLRRLR")):

        # Light up both ends of each filament
        for j in range(0,4):
            lattice[end][j] = [1,0,0]
            
            other = end.other()
            lattice[other][j] = [0,0,1]




def get_vertex_down_ends(v: VertexRef):
    return [end for end in VERTEX[0,0].ends_cw() if end.top]

def randown(v: EndRef):
    return random.choice(get_vertex_down_ends(VERTEX[1,2]))


current = VERTEX[1,3]

while True:
    lattice.clear()

    i = int(time.monotonic()*10) % 6
    for j, end in enumerate(HEX[2,0].rotate(i).ends()):
        if j % 3 == 0:
            continue
        lattice[end][0][j % 3] = 1

        other = end.other()
        lattice[other][2][j % 3] = 1

    #down = randown(current)
    # Down is a down-pointing end
    lattice.show()
    

# Send frames