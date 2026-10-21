"""Reproducible local HTTP smoke test; generated test artwork, no product claims."""

import argparse
import json
import sys
import time
import wave
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ecom_video.media import font_path


def make_fixtures(folder):
    folder.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(str(font_path()), 42)
    for i, (bg, ink, title) in enumerate(
        [("#dceaf5", "#27496d", "随行杯 / 外观"), ("#dcece4", "#385d50", "随行杯 / 细节")]
    ):
        im = Image.new("RGB", (720, 1280), bg)
        draw = ImageDraw.Draw(im)
        draw.text((65, 100), "流程测试素材", fill=ink, font=font)
        draw.rounded_rectangle((210, 360, 510, 890), radius=70, fill=ink)
        draw.rounded_rectangle((185, 320, 535, 405), radius=30, fill="#899eb1")
        draw.ellipse((220, 322, 500, 350), fill="#becbd7")
        draw.text((65, 1050), title, fill=ink, font=font)
        im.save(folder / f"product-{i + 1}.png")
    with wave.open(str(folder / "silence.wav"), "wb") as f:
        f.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        f.writeframes(b"\x00\x00" * 16000 * 4)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8765")
    p.add_argument("--out", default="var/smoke")
    args = p.parse_args()
    folder = Path(args.out).resolve()
    make_fixtures(folder)
    with httpx.Client(base_url=args.url, timeout=30) as c:
        c.headers["X-Workflow-Token"] = c.get("/api/session").raise_for_status().json()["token"]
        j = (
            c.post(
                "/api/jobs",
                json={
                    "title": "P0 示例 · 随行杯外观",
                    "script": "展示杯身的整体外观\n近距离看看杯口细节",
                    "seconds": 2,
                },
            )
            .raise_for_status()
            .json()
        )
        jid = j["id"]
        for name, kind in [
            ("product-1.png", "image"),
            ("product-2.png", "image"),
            ("silence.wav", "audio"),
        ]:
            with (folder / name).open("rb") as f:
                c.post(
                    f"/api/jobs/{jid}/assets", data={"kind": kind}, files={"file": (name, f)}
                ).raise_for_status()
        c.post(f"/api/jobs/{jid}/submit").raise_for_status()
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            j = c.get("/api/jobs/" + jid).raise_for_status().json()
            if j["status"] in ("needs_review", "failed", "blocked"):
                break
            time.sleep(0.5)
        if j["status"] != "needs_review":
            raise RuntimeError(f"Smoke failed: {j['status']}: {j['error']}")
        for kind, name in [
            ("video", "output.mp4"),
            ("subtitles", "subtitles.srt"),
            ("manifest", "manifest.json"),
            ("audit", "audit.json"),
            ("qc", "qc.json"),
        ]:
            r = c.get(f"/api/jobs/{jid}/artifacts/{kind}").raise_for_status()
            (folder / name).write_bytes(r.content)
        (folder / "job.json").write_text(
            json.dumps(j, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "job_id": jid,
                    "status": j["status"],
                    "output_dir": str(folder),
                    "evidence": "real HTTP / real FFmpeg / synthetic fixtures; human review pending",
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
