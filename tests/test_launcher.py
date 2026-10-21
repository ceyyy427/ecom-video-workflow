import os
import signal
import socket
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path

import httpx
import pytest


@pytest.mark.skipif(
    os.name != "posix", reason="POSIX process-group shutdown regression; Windows unverified"
)
def test_supervisor_term_stops_children(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen(
        [sys.executable, "-m", "ecom_video", "--data", str(tmp_path), "--port", str(port)],
        cwd=Path(__file__).resolve().parents[1],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 15
        with httpx.Client(timeout=0.5) as client:
            while True:
                try:
                    assert client.get(f"http://127.0.0.1:{port}/api/health").status_code == 200
                    break
                except httpx.TransportError:
                    if time.monotonic() > deadline:
                        raise AssertionError("launcher did not start") from None
                    time.sleep(0.1)
            time.sleep(1)  # All three processes must survive startup, not only the API.
            assert proc.poll() is None
            proc.terminate()
            assert proc.wait(timeout=12) == 0, (
                "Supervisor must handle SIGTERM and clean up children"
            )
            with pytest.raises(httpx.TransportError):
                client.get(f"http://127.0.0.1:{port}/api/health")
    finally:
        with suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=12)
