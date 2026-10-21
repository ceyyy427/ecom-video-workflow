"""Create explicitly fictional product inputs; actual local VLM is tested separately."""

import json
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "examples/p8-live"
OUT.mkdir(parents=True, exist_ok=True)
LINES = [
    "喜欢简洁，先看这只杯子的配色。",
    "奶白杯身，搭配深色杯盖。",
    "镜头靠近，看看杯盖上的开口。",
    "再放回桌边，和书本一起看看整体。",
    "喜欢这样的外观，再了解它的细节。",
]
(OUT / "script.txt").write_text("\n".join(LINES))
(OUT / "product.txt").write_text(
    "拾光随行杯（虚构演示商品）\n奶白色杯身。\n深色杯盖，顶部有开口。\n桌边场景中有书本、电脑与帆布包。\n本商品及画面为示例，不是真实在售商品或客户实拍。\n没有容量、材质、保温、防漏或测评数据，不可据此外推功能。"
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
    parts.append(np.zeros(9600 if i < len(LINES) - 1 else 24000, dtype="<i2"))
with wave.open(str(OUT / "voice.wav"), "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(48000)
    w.writeframes(np.concatenate(parts).tobytes())
# Deliberately shuffled order: desk setting, cap close-up, whole product.
# These are controlled still-image animations, NOT filmed product action.
for i, (name, crop) in enumerate(
    [
        ("lifestyle.png", ""),
        ("detail.png", "crop=iw*0.66:ih*0.5:iw*0.17:ih*0.19,"),
        ("hero.png", ""),
    ]
):
    src = ROOT / "examples/p4/assets" / name
    vf = (
        crop
        + "scale=1080:-2,zoompan=z='1+0.08*on/239':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=240:s=540x960:fps=30,setsar=1"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(src),
            "-vf",
            vf,
            "-frames:v",
            "240",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-pix_fmt",
            "yuv420p",
            "-threads",
            "1",
            str(OUT / f"take-{i}.mp4"),
        ],
        check=True,
    )
# Encode the concatenation once. No source captions/name hints are supplied to the VLM.
(OUT / "concat.txt").write_text("\n".join(f"file 'take-{i}.mp4'" for i in range(3)))
subprocess.run(
    [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(OUT / "concat.txt"),
        "-c",
        "copy",
        str(OUT / "素材01.mp4"),
    ],
    check=True,
)
shutil.copy2(ROOT / "examples/p4/assets/hero.png", OUT / "商品图.png")
shutil.copy2(ROOT / "examples/p4/assets/ambient-original.wav", OUT / "music.wav")
(OUT / "source.json").write_text(
    json.dumps(
        {
            "notice": "FICTIONAL PRODUCT / image-based animation / system voice; NOT customer or live-action footage",
            "source_images": "examples/p4/assets; prior project generated illustration assets",
            "clip_order": [
                {"start": 0, "end": 8, "content": "桌边环境"},
                {"start": 8, "end": 16, "content": "杯盖近景"},
                {"start": 16, "end": 24, "content": "商品全貌"},
            ],
            "labels_use": "manual visual QC only, not model input or matching fixture",
            "voice": "macOS Tingting, 185 wpm; automated synthesis, requires human listening",
        },
        ensure_ascii=False,
        indent=2,
    )
)
print(OUT)
