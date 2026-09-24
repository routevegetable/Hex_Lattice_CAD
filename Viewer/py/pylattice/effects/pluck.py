

# Paint waves over the whole lattice
# Scalar field selects the hue
import math
from pylattice.examples.colors import hsv, vary
from pylattice.fields.types import ScalarField
from pylattice.examples.tempo import ZERO, Event, psweep, sweep
from pylattice.graph import EdgeClass, EdgeRef, EndRef, Graph
from pylattice.lattice_writer import LatticeWriter
from pylattice.fields.types import Slot
from pylattice.runner.types import Effect

def wobble(now: Event, lattice: LatticeWriter, edge: EdgeRef, p: int, amp: float, filament_offset: int, hue: float):
    end, other = edge.ends()
    
    y = math.sin(psweep(now, p, 0, 2 * math.pi))
    
    # Mult by amplitude
    y = y * (amp + 0.1) / 2

    MIDDLE_PT = 0.5
    
    center_dist = abs(y)
    middle_dist = abs(MIDDLE_PT - abs(y))
    max_dist = abs(1 - abs(y))
    
    DIST_T = 0.51
    
    # Larger dist is lower brightness
    center_brightness = 1 - (center_dist / DIST_T) if center_dist < DIST_T else 0
    middle_brightness = 1 - (middle_dist / DIST_T) if middle_dist < DIST_T else 0
    max_brightness = 1 - (max_dist / DIST_T) if max_dist < DIST_T else 0
    
    # Center
    if center_brightness > 0.01:
        c = list(hsv(hue, 0.7, center_brightness))
        idx = (filament_offset)
        lattice[end][idx] = c
        lattice[other][idx] = c
    
    # Middle
    if middle_brightness > 0.01:
        c = list(hsv(hue, 0.7, middle_brightness))
        idx = (filament_offset + (1 if y > 0 else 2)) % 4
        lattice[end][idx] = c
        lattice[other][idx] = c
                    
    # Max
    if max_brightness > 0.01 and False:
        lattice[end][3] = [max_brightness] * 3
        lattice[other][3] = [max_brightness] * 3
                    

class Pluck(Effect):
    """
    3 sets of strings vibrating at a field-dependent amplitude
    """
    
    a_amp: Slot
    b_amp: Slot
    c_amp: Slot
    period: Slot
    
    def render(self, now: Event, lattice: LatticeWriter, graph: Graph):
        a_amp, b_amp, c_amp, period = self.a_amp, self.b_amp, self.c_amp, self.period
        
        first = True
        # A: Horizontal strings
        for ty in range(0, graph.height):
            for start in [
                graph.TILE[0,ty].bottom_end(EdgeClass.E), # DEF vertex, pointing right
                graph.TILE[0,ty].bottom_end(EdgeClass.A) # ABC vertex, pointing right
            ]:
                a_path = start.path("RL" * graph.width)
                
                for end in a_path:
                    other = end.other()
                    
                    # Average amplitude of both ends
                    amp = (c_amp.get(now, end) + c_amp.get(now, other)) / 2
                    
                    # Average period too, between 1 and 500ms
                    p = (period.get(now, end) + period.get(now, other)) / 2
                    p = 120
                    
                    wobble(now, lattice, end, p, amp, 0, a_amp.get(now, end))
                    
        # B: Right Strings
        for tx in range(0, graph.width):
            break
            for start in [
                graph.TILE[tx, 0].bottom_end(EdgeClass.E), # DEF vertex, pointing right
                graph.TILE[tx,0].bottom_end(EdgeClass.A) # ABC vertex, pointing right
            ]:
                b_path = start.path("LR" * graph.width)
                
                for end in b_path:
                    other = end.other()
                    
                    # Average amplitude of both ends
                    amp = (b_amp.get(now, end) + b_amp.get(now, other)) / 2
                    
                    # Average period too, between 1 and 500ms
                    p = 120
                    
                    wobble(now, lattice, end, p, amp, 1, 0.5)
                    
        # C: Left Strings
        for tx in range(0, graph.width):
            break
            for start in [
                graph.TILE[tx, 0].bottom_end(EdgeClass.D), # DEF vertex, pointing right
                graph.TILE[tx,0].bottom_end(EdgeClass.B) # ABC vertex, pointing right
            ]:
                c_path = start.path("RL" * graph.width)
                
                for end in c_path:
                    other = end.other()
                    
                    # Average amplitude of both ends
                    amp = (c_amp.get(now, end) + c_amp.get(now, other)) / 2
                    
                    # Average period too, between 1 and 500ms
                    p = 120
                    
                    wobble(now, lattice, end, p, amp, 1, a_amp.get(now, end))
            
            

        
