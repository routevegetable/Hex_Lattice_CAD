"""A REST server and a page to drive it, both reading one Console.

    serve(console)      # starts uvicorn on its own thread, returns it

Everything structured is a dataclass - FastAPI serialises those directly, so
there are no dictionaries crossing the wire by hand. The page itself lives in
static/, read per request, so editing it only needs a browser reload.
"""
import asyncio
import threading
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from dataclasses import asdict

from pylattice.instrument.console import (Console, ControlInfo, Knob, PresetView,
                                          Rig, Stats)
from pylattice.instrument.patch import Patch

STATIC = Path(__file__).parent / "static"


def make_app(console: Console) -> FastAPI:
    app = FastAPI(title="lattice")
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", response_class=HTMLResponse)
    def page() -> str:
        return (STATIC / "index.html").read_text()

    @app.get("/mobile", response_class=HTMLResponse)
    def mobile() -> str:
        """The touch layout - same API, built for a small landscape screen."""
        return (STATIC / "mobile.html").read_text()

    @app.get("/stats")
    def stats() -> Stats:
        return console.get_stats()

    @app.get("/controls")
    def controls() -> list[ControlInfo]:
        """Every knob and pad the instrument watches, and what it drives."""
        return console.controls()

    # Pushed rather than polled: the knobs move continuously and a UI that
    # asked would either be behind them or ask far too often.
    KNOB_HZ = 10

    @app.websocket("/ws/knobs")
    async def knobs(socket: WebSocket):
        """Knobs both ways.

        Out: every CC number, ten times a second, for as long as anyone is
        listening. In: `{"cc": 77, "value": 64}` to move one, which lands the
        same way a hand on the desk would.
        """
        await socket.accept()

        async def push():
            """A frame per tick, and never a wait for room to put one.

            A frame is the whole state of the desk rather than a change to it,
            so one that could not be sent is worth nothing: the next frame
            says everything it would have. That makes dropping the right
            answer, and it is why this loop never awaits the send.

            The send goes out as a task of its own and the loop only sleeps.
            If that task is still going when the next tick comes round -
            a client that has stopped reading, a link that has stalled - the
            tick is skipped rather than queued, so there is at most one frame
            in flight and never a backlog to work through. A slow client slows
            only itself.
            """
            sending: asyncio.Task | None = None

            try:
                while True:
                    if sending is None or sending.done():
                        if sending is not None:
                            # A send that failed - the far end gone - raises
                            # here, which is how this loop finds out.
                            sending.result()

                        # console.knobs takes the render lock, which the loop
                        # holds for a frame - under a millisecond, so the event
                        # loop can wear it.
                        frame = {str(cc): asdict(knob)
                                 for cc, knob in console.knobs().items()}
                        sending = asyncio.create_task(socket.send_json(frame))

                    await asyncio.sleep(1 / KNOB_HZ)
            finally:
                # Going away mid-send: nothing is waiting on this task, so it
                # has to be called off rather than left to finish alone.
                if sending is not None and not sending.done():
                    sending.cancel()

        async def pull():
            while True:
                moved = await socket.receive_json()

                try:
                    console.set_cc(int(moved["cc"]), int(moved["value"]))
                except (KeyError, TypeError, ValueError):
                    pass            # not something we can act on; keep listening

        try:
            await asyncio.gather(push(), pull())
        except WebSocketDisconnect:
            pass

    @app.get("/rig")
    def rig() -> Rig:
        """What can be patched. Everything that *is* patched is in /current."""
        return console.describe()

    @app.put("/muted")
    def mute(names: list[str]) -> Rig:
        """Silence exactly these effects, and unsilence the rest. Muting is
        for looking at one thing at a time: it is not part of a preset, and
        selecting another preset clears it."""
        try:
            console.set_muted(names)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
        return console.describe()

    @app.get("/presets")
    def all_presets() -> dict[int, PresetView]:
        """Every preset the bank holds, each against its file."""
        return console.all_presets()

    @app.get("/presets/{number}")
    def read_preset(number: int) -> PresetView:
        """One preset: its live side, and the file it came from."""
        try:
            return console.read_preset(number)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

    @app.put("/presets/{number}")
    def write_preset(number: int, patch: Patch) -> PresetView:
        """Put a patch into a preset's live side.

        The patch is the whole picture, knobs included - nothing is merged. If
        this is the preset that is playing the rig hears it at once; writing to
        any other one is silent until something selects it.
        """
        try:
            console.write_preset(number, patch)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
        return console.read_preset(number)

    @app.post("/presets/{number}/select")
    def select_preset(number: int) -> PresetView:
        """Play what is in this preset's live side."""
        try:
            console.select_preset(number)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
        return console.read_preset(number)

    @app.post("/presets/{number}/commit")
    def commit_preset(number: int) -> PresetView:
        """Write this preset's live side out to its file."""
        try:
            console.commit_preset(number)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
        return console.read_preset(number)

    @app.post("/presets/{number}/revert")
    def revert_preset(number: int) -> PresetView:
        """Drop this preset's edits and read its file back."""
        try:
            console.revert_preset(number)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
        return console.read_preset(number)

    return app


def serve(console: Console, host: str = "127.0.0.1", port: int = 8800) -> threading.Thread:
    """Run the API on its own daemon thread, so the render loop keeps the main one."""
    config = uvicorn.Config(make_app(console), host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, name="lattice-api", daemon=True)
    thread.start()
    print(f"api on http://{host}:{port}")
    return thread
