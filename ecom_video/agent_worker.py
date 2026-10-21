"""Bounded local Agent scheduler. Existing workers own inference and rendering."""

import argparse
import signal
import threading
from pathlib import Path

from .agent_runtime import Runtime
from .db import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    runtime = Runtime(args.data, Store(Path(args.data) / "workflow.db"))
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    while not stop.is_set():
        runtime.tick()
        if args.once:
            return
        stop.wait(1)


if __name__ == "__main__":
    main()
