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
from fastapi.responses import HTMLResponse, RedirectResponse
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

    @app.get("/current")
    def current():
        """Whichever preset is playing. There is nothing else to it - the bank
        keeps that preset up with the knobs, so this is just its number."""
        number = console.selected()

        if number is None:
            raise HTTPException(status_code=404, detail="no preset is selected")

        return RedirectResponse(f"/presets/{number}")

    @app.post("/current")
    def write_current(patch: Patch) -> PresetView:
        """Apply a patch. The UI posts the whole thing, every time."""
        try:
            console.write_settings(patch)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
        return console.read_preset(console.selected())

    @app.get("/presets/{number}")
    def read_preset(number: int) -> PresetView:
        try:
            return console.read_preset(number)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

    @app.get("/presets")
    def all_presets() -> dict[int, PresetView]:
        """Every preset the bank holds, each flagged dirty or not."""
        return console.all_presets()

    @app.post("/presets/{number}/duplicate")
    def duplicate_preset(number: int) -> PresetView:
        """Copy what is playing into a preset and move there, unsaved."""
        try:
            console.duplicate_current_to(number)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
        return console.read_preset(number)

    @app.post("/presets/{number}/save")
    def save_preset(number: int) -> PresetView:
        """Write a preset's edits out."""
        try:
            console.save_preset(number)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
        return console.read_preset(number)

    @app.post("/presets/{number}/revert")
    def revert_preset(number: int) -> PresetView:
        """Throw a preset's edits away and read its file back."""
        try:
            console.revert_preset(number)
            return console.read_preset(number)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

    @app.post("/presets/{number}/store")
    def store_preset(number: int) -> PresetView:
        try:
            console.store_current_to(number)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
        return console.read_preset(number)

    @app.post("/presets/{number}/load")
    def load_preset(number: int) -> PresetView:
        try:
            console.load_current_from(number)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from None
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
