

from py.lib.frame import EndFrame, ModuleFrame
from py.lib.graph import EndRef
from py.lib.lattice_client import LatticeClient


class LatticeWriter:

    def __init__(self, cols: int, rows: int):
        self._cols = cols
        self._rows = rows
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
                self._client.send_module(x,y, self._module_frames[x][y])