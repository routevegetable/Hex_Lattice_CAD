* Have the app consume the module map and address modules directly, rather than rely on the module server. Then it can do filament order overrides etc... And the module server stays relevant for hexnet things which aren't hexagon modules, and doesn't need to have multi-lattice support added, etc...

* Could have a 'mapper' app to generate the module map and do flagging and stuff.

* Publish to different parts of the lattice from multiple running apps.

* Separate the repos out. "CAD/Viewer" no longer really reflects what is in here.

* Ability to (re)map field controls (notes and CCs) in a patch. Rather than a field naming a control directly by number, the 'comment' becomes an ID.

* Some kind of usable module mapping experience for small touch screen.

* Some kind of cute Web UI preview for fields and effects.

* Rather than a custom expression tree type for fields, allow arbitrary python in a slot.

* A patch includes a number of effects. Not all of them. Prevents UI crowding and confusing behavior.

* Field+Effect hierarchy/categorization. Field/Effect arrays?

* Slots for things other than fields, like color maps and envelopes.

* Some way that a 'nonterminal' field can have memory or parameters. Hysteresis etc...

* Synced LFO field?






FFT things, where we have:
* A field which just provides a constant for a given frequency band
* A field which is a spectrogram moving from L to R, with lowest frequencies at the bottom
* Operator that maps a given frequency range to a magnitude
* “Bar Graph” field


Make field evaluation non-capturing (purely based on patch lookup)
Replace expression trees with straight python to evaluate
Make control detection dynamic rather than based on static analysis, to support that
Make notes remappable and able to be triggered from the web UI.
Pipeline Is now: Notes/ccs -> fields/operators -> effects
Web UI test/preview area
Web UI beat detection/FFT stuff which can trigger notes and CCs
The ability to mark a CC as ‘force restore’?
Every effect’s UI shows pic of the/a MIDI controller, with the buttons/knobs labeled appropriately.
An interp(f1, f2, f3) operator, which takes a CC and interpolates between multiple input fields