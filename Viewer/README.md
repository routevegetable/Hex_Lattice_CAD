# Hex Lattice

## App
This lives under `py`, and generates module frames; sends them out over UDP multicast, where they are picked up by both the module server and the viewer (run `serve.py`).

## To Install

Needs [uv](https://docs.astral.sh/uv/) and portmidi (a C library, loaded by ctypes - there is no Python package for it).

macOS:

```sh
brew install uv portmidi
```

Linux (Debian/Ubuntu/Raspberry Pi OS):

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
sudo apt install libportmidi0
```

Then:

```sh
uv sync --project py
```

That reads `py/.python-version` and fetches PyPy 3.11 if it isn't already there.
The app runs on PyPy - it renders a frame about 5x faster than CPython. Keep
code PyPy-compatible: Python 3.11 syntax, no CPython-only C extensions.
`python-rtmidi` is one of those, so it is marked CPython-only in
`py/pyproject.toml` and MIDI goes through portmidi instead.

## To Run

The effects app:

```sh
cd py
uv run -m pylattice.instrument
```

The tester app:

```sh
cd py
uv run -m pylattice.examples.tester
```

The viewer, in another shell (stdlib only, so any python will do):

```sh
python3 serve.py
```

## Check

```sh
pypy3 -m py_compile $(find py/pylattice -name '*.py')
```
