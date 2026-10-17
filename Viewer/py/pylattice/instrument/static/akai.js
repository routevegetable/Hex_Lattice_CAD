// Where each field lives on the Akai MPD232: controller mode, Q-Link bank 1, pad
// bank A. Copied from docs/akai_mpd232.svg - hardware.py's akai profile is still
// the BeatStep's, so nothing on the server can say. Edit this when a control gets
// a field; `null` is a control nothing is mapped to yet.
//
// The page draws its right-hand side from this. Fields not named here are listed
// below the diagram instead.
const AKAI = {
  name: 'Akai MPD232',
  knobs:   [null, null, null, null, null, null, null, null],
  faders:  [
    {field: 'fader_a', cc: 12}, {field: 'fader_b', cc: 13},
    {field: 'param_a', cc: 14}, {field: 'param_b', cc: 15},
    null, null, null, null,
  ],
  buttons: [null, null, null, null, null, null, null, null],
  // As they sit on the unit: pad 13 is top left, pad 1 bottom left.
  pads: [
    [{n: 13, field: 'strobe0', note: 81}, {n: 14, field: 'strobe1', note: 83},
     {n: 15, field: 'strobe2', note: 84}, {n: 16, field: 'burst', note: 86}],
    [{n: 9, field: 'ripple', note: 74}, {n: 10, field: 'ripple2', note: 76},
     {n: 11, field: 'wipe1', note: 77}, {n: 12, field: 'wipe2', note: 79}],
    [{n: 5, field: 'trace', note: 67}, {n: 6, field: 'random', note: 69},
     {n: 7, field: 'fire', note: 71}, {n: 8, field: 'bloom', note: 72}],
    [{n: 1}, {n: 2}, {n: 3}, {n: 4}],
  ],
};
