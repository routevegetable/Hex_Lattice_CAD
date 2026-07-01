#!/usr/bin/env python3
"""Tiny static server for the Hinge Hexagon viewer.

Serves index.html and the hinge_obj/ assets so the browser can fetch the OBJ
(loading local files directly via file:// is blocked by CORS).

Usage:
    python3 serve.py            # serves on http://localhost:8765
    python3 serve.py 9000       # custom port
"""
import http.server
import socketserver
import sys
import webbrowser
from pathlib import Path

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
ROOT = Path(__file__).resolve().parent


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        # No caching, so edits to index.html show up on refresh.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        print("  ", fmt % args)


def main():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        url = f"http://localhost:{PORT}/index.html"
        print(f"Hinge Hexagon viewer serving at {url}")
        print("Press Ctrl+C to stop.")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
