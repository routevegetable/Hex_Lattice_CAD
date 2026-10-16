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