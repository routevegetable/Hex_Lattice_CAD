"""A REST server and a page to drive it, both reading one Console.

    serve(console)      # starts uvicorn on its own thread, returns it

Everything structured is a dataclass - FastAPI serialises those directly, so
there are no dictionaries crossing the wire by hand. The page itself lives in
static/, read per request, so editing it only needs a browser reload.
"""
import threading
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

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

    @app.get("/knobinfo")
    def knob() -> Knob | None:
        """The control that moved last. Null until one does."""
        return console.last_cc()

    @app.get("/rig")
    def rig() -> Rig:
        """What can be patched. Everything that *is* patched is in /current."""
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
