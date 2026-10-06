"""`kiozesim-ui`: start the web server (UI-016)."""

from __future__ import annotations

import argparse

import uvicorn

from kiozesim_ui.app import app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="kiozesim-ui", description="kiozesim web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
