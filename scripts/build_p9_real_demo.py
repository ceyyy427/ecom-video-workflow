"""Build a licensed live-action scene demo; no fake customer SKU or model labels."""

import hashlib
import json
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "examples/p9-real"
LINES = [
    "咖啡倒入，给工作留个小停顿。",
    "木桌和电脑旁，先看看这只咖啡杯。",
    "换个场景，书本和电脑旁，也能放一杯咖啡。",
]
(OUT / "script.txt").write_text("\n".join(LINES))
(OUT / "product.txt").write_text(
    "杯具场景演示：两种杯型，不是同一商品，不是客户素材。\n"
    "场景一：木桌、电脑旁的棕色咖啡杯，有倒咖啡的可见动作。\n"
    "场景二：白色桌面、书本和电脑旁的透明杯，有倒咖啡的可见动作。\n"
    "素材作者 Cup of Couple，来自 Pexels，来源和许可见 source.json。\n"
    "只作场景选段演示，不宣称品牌、材质、容量、保温效果或测评结果。\n"
)
parts = []
for i, line in enumerate(LINES):
    txt, aiff, wav = [OUT / f"line-{i}.{ext}" for ext in ["txt", "aiff", "wav"]]
    txt.write_text(line)
    subprocess.run(
        ["say", "-v", "Tingting", "-r", "185", "-f", str(txt), "-o", str(aiff)], check=True
    )
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(aiff), "-ar", "48000", "-ac", "1", str(wav)],
        check=True,
    )
    with wave.open(str(wav), "rb") as w:
        parts.append(np.frombuffer(w.readframes(w.getnframes()), dtype="<i2"))
    parts.append(np.zeros(12000 if i < 2 else 24000, dtype="<i2"))
with wave.open(str(OUT / "voice.wav"), "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(48000)
    w.writeframes(np.concatenate(parts).tobytes())
shutil.copy2(ROOT / "examples/p4/assets/ambient-original.wav", OUT / "music.wav")
rows = []
for video_id, title, suffix, name in [
    ("6177761", "coffee-next-to-computer-on-a-table", "24", "素材A.mp4"),
    ("8472298", "a-person-pouring-a-cup-of-coffee-beside-a-laptop", "25", "素材B.mp4"),
]:
    path = OUT / "originals" / (video_id + ".mp4")
    shutil.copy2(path, OUT / name)
    probe = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_name,width,height,r_frame_rate",
                "-of",
                "json",
                str(path),
            ]
        )
    )
    rows.append(
        {
            "id": video_id,
            "file": str(path.relative_to(ROOT)),
            "uploaded_as": name,
            "source_page": f"https://www.pexels.com/video/{title}-{video_id}/",
            "download_url": f"https://videos.pexels.com/video-files/{video_id}/{video_id}-hd_1080_1920_{suffix}fps.mp4",
            "author": "Cup of Couple",
            "license": "https://www.pexels.com/license/",
            "checked_date": "2026-10-16",
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "measured_probe": probe,
            "derivation": "Byte-identical copy under neutral upload filename; edits only in timeline.",
        }
    )
(OUT / "source.json").write_text(
    json.dumps(
        {
            "notice": "Licensed live-action stock; two different cups, a scene collection, NOT a customer SKU or endorsement.",
            "sources": rows,
            "license_review": "Official Pexels source pages and license read on 2026-10-16. Free use and editing permitted. No unaltered resale, stock redistribution, implied endorsement or trademark use. Other third-party rights may apply.",
            "voice": "macOS Tingting synthetic voice; human listening pending",
            "music": "Project original generated ambient score, examples/p4/assets/ambient-original.wav",
            "metadata_use": "Provenance and manual QC only; not injected into model observations or scores.",
        },
        ensure_ascii=False,
        indent=2,
    )
)
print(OUT)
