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

from pylattice.instrument.console import Console, Rig, Stats
from pylattice.instrument.patch import Patch

STATIC = Path(__file__).parent / "static"


def make_app(console: Console) -> FastAPI:
    app = FastAPI(title="lattice")
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", response_class=HTMLResponse)
    def page() -> str:
        return (STATIC / "index.html").read_text()

    @app.get("/stats")
    def stats() -> Stats:
        return console.get_stats()

    @app.get("/rig")
    def rig() -> Rig:
        """What can be patched. Everything that *is* patched is in /current."""
        return console.describe()

    @app.get("/current")
    def current() -> Patch:
        return console.read_settings()

    @app.post("/current")
    def write_current(patch: Patch) -> Patch:
        try:
            console.write_settings(patch)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
        return console.read_settings()

    @app.get("/presets/{number}")
    def read_preset(number: int) -> Patch:
        try:
            return console.read_preset(number)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

    @app.post("/presets/{number}/store")
    def store_preset(number: int) -> Patch:
        try:
            console.store_current_to(number)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
        return console.read_preset(number)

    @app.post("/presets/{number}/load")
    def load_preset(number: int) -> Patch:
        try:
            console.load_current_from(number)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
        return console.read_settings()

    return app


def serve(console: Console, host: str = "127.0.0.1", port: int = 8800) -> threading.Thread:
    """Run the API on its own daemon thread, so the render loop keeps the main one."""
    config = uvicorn.Config(make_app(console), host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, name="lattice-api", daemon=True)
    thread.start()
    print(f"api on http://{host}:{port}")
    return thread
