"""Create local synthetic narration and reference frames from licensed originals."""

import argparse
import json
import subprocess
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "examples/p10-real"
DEMOS = {
    "opening": {
        "id": "7551085",
        "lines": ["握稳瓶身，轻轻拧开瓶盖。", "看一看，瓶口和瓶身的细节。"],
        "time": 0.1,
        "crop": "crop=2500:1560:0:600",
        "fact": "画面为透明瓶、红色瓶盖，手部旋开瓶盖，之后展示瓶身。",
    },
    "pouring": {
        "id": "3756147",
        "lines": ["倒水，留一刻从容。", "再看看瓶身，线条简单清楚。"],
        "time": 6,
        "crop": "crop=800:2200:1300:1700",
        "fact": "画面为同一只深色透明瓶，向杯中倒水，之后放回台面。",
    },
    "pouring-flask": {
        "id": "7476644",
        "title": "金属瓶 · 倒入实拍动作演示",
        "lines": ["倒入杯中，慢慢来。", "握住瓶身，让水流细一些。"],
        "time": 1,
        "crop": "crop=2200:1100:1600:400",
        "fact": "实拍画面是一只银色金属瓶向杯中倒入可见液体，背景为海边。",
    },
}
parser = argparse.ArgumentParser()
parser.add_argument("names", nargs="*", choices=list(DEMOS))
args = parser.parse_args()
for name, d in DEMOS.items():
    if args.names and name not in args.names:
        continue
    out = BASE / name
    out.mkdir(exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-ss",
            str(d["time"]),
            "-i",
            str(BASE / "originals" / f"pexels-{d['id']}.mp4"),
            "-frames:v",
            "1",
            "-vf",
            d["crop"] + ",scale=640:-2",
            str(out / "reference.jpg"),
        ],
        check=True,
    )
    (out / "script.txt").write_text("\n".join(d["lines"]))
    (out / "product.txt").write_text(
        d["fact"]
        + "\n授权实拍素材的单品动作技术演示，非客户真实商品或型号鉴定。不宣称品牌、功能、性能、容量。\n参见 examples/p10-real/sources.json。"
    )
    parts = []
    for i, line in enumerate(d["lines"]):
        t = out / f"line-{i}.txt"
        a = out / f"line-{i}.aiff"
        w = out / f"line-{i}.wav"
        t.write_text(line)
        subprocess.run(
            ["say", "-v", "Tingting", "-r", "185", "-f", str(t), "-o", str(a)], check=True
        )
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(a), "-ar", "48000", "-ac", "1", str(w)],
            check=True,
        )
        with wave.open(str(w), "rb") as f:
            parts.append(np.frombuffer(f.readframes(f.getnframes()), dtype="<i2"))
        parts.append(np.zeros(12000 if i == 0 else 24000, dtype="<i2"))
    with wave.open(str(out / "voice.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(np.concatenate(parts).tobytes())
(BASE / "demos.json").write_text(json.dumps(DEMOS, ensure_ascii=False, indent=2))
