#!/usr/bin/env bash
# Run the LED emulator (ts/examples/app.ts) and auto-restart it whenever the file
# or any of its ts/lib dependencies change. `deno --watch` does the watching.
#
#   ./run-app.sh                 # uses HINGE_SOCK or /tmp/hinge-leds.sock
#   HINGE_SOCK=/tmp/x.sock ./run-app.sh
#
# (Start serve.py separately — it creates the socket + serves the viewer.)
set -euo pipefail
cd "$(dirname "$0")/ts/examples"
# -A: app.ts uses npm:@julusian/midi (native addon for MIDI clock) which needs
# broad permissions.
exec deno run --watch -A app.ts "$@"
