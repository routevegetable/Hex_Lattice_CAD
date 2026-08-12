import time
from typing import Optional
from py.lib.frame import EndFrame, ModuleFrame
from py.lib.graph import VERTEX, TileRef, VertexClass, EndRef
from py.lib.lattice_client import LatticeClient
from py.lib.lattice_writer import LatticeWriter

ROWS = 4
COLS = 4

lattice = LatticeWriter(COLS, ROWS)


# Clockwise
for i, v_end in enumerate(VERTEX[1,2].ends_cw()):

    # Draw a 'line'
    for dist, end in enumerate(v_end.path("RRRLRRLRRLR")):

        for j in range(0,4):
            # Light up both ends
            lattice[end][j][i] = 1-dist/10
            

            other = end.other()
            lattice[other][j][i] = 1-(dist + 1)/10
        
# Send frames
lattice.show()