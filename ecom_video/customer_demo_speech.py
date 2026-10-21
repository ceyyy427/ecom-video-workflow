"""Explicit local demo speech only; never a network or voice-cloning fallback."""

import os
import subprocess
from pathlib import Path

from .host_os import WINDOWS


def synthesize(text, output):
    text, output = Path(text).resolve(), Path(output).resolve()
    if WINDOWS:
        powershell = (
            Path(os.environ["SYSTEMROOT"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        )
        script = Path(__file__).resolve().parents[1] / "scripts/customer_speech.ps1"
        subprocess.run(
            [
                str(powershell),
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(script),
                "-TextPath",
                str(text),
                "-OutputPath",
                str(output),
            ],
            check=True,
            timeout=60,
        )
    else:
        import sys

        if sys.platform != "darwin":
            raise ValueError("该系统请通过 --voice-file 提供与 script.txt 对应的本机配音")
        aiff = output.with_suffix(".aiff")
        subprocess.run(
            ["say", "-v", "Tingting", "-r", "240", "-f", str(text), "-o", str(aiff)],
            check=True,
            timeout=60,
        )
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                str(aiff),
                "-ac",
                "1",
                "-ar",
                "48000",
                str(output),
            ],
            check=True,
            timeout=30,
        )


def demo_data(workspace, data=None):
    """Reuse only the stopped, blank setup rehearsal beside the new evidence folder."""
    workspace = Path(workspace).resolve()
    if data is None:
        return workspace / "runtime"
    import sqlite3
    from contextlib import closing

    from .maintenance import inspect_database

    data = Path(data).resolve()
    if data.parent != workspace.parent or data == workspace:
        raise ValueError("仅允许验收目录旁的空白首次配置数据目录")
    with closing(sqlite3.connect((data / "workflow.db").as_uri() + "?mode=ro", uri=True)) as db:
        inspect_database(db, quiescent=True)
        for table in ("jobs", "customer_projects", "products", "reviews"):
            if db.execute(f'SELECT 1 FROM "{table}" LIMIT 1').fetchone():
                raise ValueError("首次配置数据必须空白；不能修改已有商品或审核记录")
    return data
