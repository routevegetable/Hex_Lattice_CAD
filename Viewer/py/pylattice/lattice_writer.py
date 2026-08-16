

import math
from . import format
from .frame import EdgeFrame, EndFrame, Ends, ModuleFrame
from .graph import EndRef
from .lattice_client import LatticeClient


class LatticeWriter:

    def __init__(self, cols: int, rows: int, fmt=format.STANDARD_MODULE):
        self._cols = cols
        self._rows = rows
        self._fmt = fmt
        self._client = LatticeClient()

        # Instantiate a matrix of module frames
        self._module_frames: list[list[ModuleFrame]] = [
            [ModuleFrame.blank() for _ in range(0,rows)] for _ in range(0,cols)
        ]
    
    def __getitem__(self, end: EndRef) -> EndFrame:
        return self.get_end_frame(end)

    # Get an end frame from its module - wrap around
    def get_end_frame(self, end_ref: EndRef) -> EndFrame:
        module_x = (end_ref.tile.x // 2) % self._cols
        module_y = end_ref.tile.y % self._rows
        return self._module_frames[module_x][module_y].get_end_frame(end_ref)

    # Send all module frames to their modules
    def show(self):
        for x in range(0, self._cols):
            for y in range(0, self._rows):
                channel_data = self._fmt.serialize(self._module_frames[x][y])
                self._client.send(x, y, channel_data)
                
    def clear(self):
        self._module_frames = [
            [ModuleFrame.blank() for _ in range(0,self._rows)] for _ in range(0,self._cols)
        ]