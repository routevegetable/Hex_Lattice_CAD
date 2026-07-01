A 'module' is two segments, side by side.
Each small-small tube (aka edge) has 4 'filaments' running from one end to the other.
These are within the tube, around the axis of the tube, in a circular pattern, and they run parallel to each other.
For a module(pair of segments), there is a schema:
edge (tube)[0..11] -> filament [0..3] -> end[0..1].

The precise mapping from edge item to spatial edge is arbitrary wrt space.
The mapping from filament item to spatial filament is arbitrary wrt space.
The mapping from end to spatial end should match between different filaments for that edge, but is arbitrary wrt space.