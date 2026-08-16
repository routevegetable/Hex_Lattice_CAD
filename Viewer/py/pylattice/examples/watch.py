#!/usr/bin/env python3
"""Watch every .py file in this directory; kill and rerun a command whenever
one changes.

    python3 watch.py -- python3 color_temp_lightning_edges.py
    python3 watch.py -- python3 four_colors.py --some-flag

Everything after `--` (or, if there's no `--`, everything after the script
name) is the command to run. Polls mtimes every POLL_SECS rather than using
an OS file-watch API/library, so it needs nothing beyond the stdlib.

Ctrl+C stops the watcher and whatever command is currently running.
"""
import os
import signal
import subprocess
import sys
import time

WATCH_DIR = os.path.dirname(os.path.abspath(__file__))
POLL_SECS = 0.5
KILL_GRACE_SECS = 3.0


def snapshot():
    """{filename: mtime} for every .py file directly in WATCH_DIR."""
    out = {}
    for name in os.listdir(WATCH_DIR):
        if name.endswith(".py"):
            path = os.path.join(WATCH_DIR, name)
            try:
                out[name] = os.stat(path).st_mtime
            except OSError:
                pass  # deleted between listdir() and stat()
    return out


def start(cmd):
    print(f"[watch] starting: {' '.join(cmd)}")
    # New process group so a kill takes any children the command spawns with it.
    return subprocess.Popen(cmd, cwd=WATCH_DIR, preexec_fn=os.setsid)


def stop(proc):
    if proc is None or proc.poll() is not None:
        return
    pgid = os.getpgid(proc.pid)
    try:
        os.killpg(pgid, signal.SIGTERM)
        proc.wait(timeout=KILL_GRACE_SECS)
    except subprocess.TimeoutExpired:
        print("[watch] process didn't exit, sending SIGKILL")
        os.killpg(pgid, signal.SIGKILL)
        proc.wait()
    except ProcessLookupError:
        pass


def main():
    args = sys.argv[1:]
    if args and args[0] == "--":
        args = args[1:]
    if not args:
        print("usage: watch.py [--] <command> [args...]", file=sys.stderr)
        sys.exit(1)

    print(f"[watch] watching *.py in {WATCH_DIR}")
    files = snapshot()
    proc = start(args)

    # Explicit handlers rather than relying on the bare `except KeyboardInterrupt`
    # a plain try/except would give "for free": when this script is launched as
    # a background job (`watch.py ... &`) from a non-interactive shell, bash sets
    # SIGINT to SIG_IGN in that child before exec, and Python only installs its
    # default int-handler-raises-KeyboardInterrupt behavior when SIGINT *wasn't*
    # already ignored at startup - so a backgrounded watch.py would silently eat
    # SIGINT forever. Installing our own handler overrides that inherited
    # disposition unconditionally, so Ctrl-C (interactive) and `kill`/`kill -TERM`
    # (background, nohup, etc.) all work the same way.
    shutdown = {"requested": False}

    def _request_shutdown(signum, frame):
        shutdown["requested"] = True

    signal.signal(signal.SIGINT, _request_shutdown)
    signal.signal(signal.SIGTERM, _request_shutdown)

    try:
        while not shutdown["requested"]:
            time.sleep(POLL_SECS)
            if shutdown["requested"]:
                break
            current = snapshot()
            if current != files:
                changed = sorted(set(current) ^ set(files)) or sorted(
                    name for name in current if current[name] != files[name]
                )
                print(f"[watch] changed: {', '.join(changed)} -> restarting")
                files = current
                stop(proc)
                proc = start(args)
            elif proc is not None and proc.poll() is not None:
                # Command exited on its own (crash or normal exit) - report it,
                # keep watching, and only restart once a file actually changes.
                print(f"[watch] command exited ({proc.returncode}), waiting for a change")
                proc = None
    finally:
        print("\n[watch] stopping")
        stop(proc)


if __name__ == "__main__":
    main()
