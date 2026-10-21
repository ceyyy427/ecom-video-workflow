"""Offline fixture render; no service, database, provider or customer media access."""

import json
import shutil
import sys
import tempfile
import wave
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ecom_video.creative import Brief, recommend
from ecom_video.media import digest, inspect_media, probe, run_checked
from ecom_video.remotion_renderer import render_remotion, style_previews
from ecom_video.storyboard import default_board


def main():
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ecom-mpt-fixture-") as temporary:
        root = Path(temporary)
        image = root / "fixture.png"
        im = Image.new("RGB", (1080, 1920), "#adbac2")
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((300, 550, 780, 1300), radius=60, fill="#ecdec4")
        im.save(image)
        voice = root / "fixture.wav"
        with wave.open(str(voice), "wb") as audio:
            audio.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
            audio.writeframes(b"\x00\x00" * 48000 * 2)
        assets = [
            {
                "id": path.stem + kind,
                "kind": kind,
                "path": path.name,
                "sha256": digest(path),
                "metadata": inspect_media(path, kind),
                "size": path.stat().st_size,
            }
            for path, kind in [(image, "image"), (voice, "audio")]
        ]
        snap = {
            "title": "字幕排版测试",
            "script": "外观 Supercalifragilisticexpialidocious 1.5L",
            "seconds": 2,
            "assets": assets,
        }
        rec = recommend(snap, Brief(format="narrated"))
        board = default_board(snap)
        board["sample"] = True
        board["creative"] = {
            "brief": rec["brief"],
            "fingerprint": rec["fingerprint"],
            "style_id": "lab",
            "brand": {"name": "合成测试素材"},
        }
        board["shots"][0].update(shot_id="fixture-shot", headline="外观", treatment="footage")
        snap["storyboard"] = board
        job = {"id": "mpt-offline-fixture", "snapshot": snap}
        first = root / "render-1"
        first.mkdir()
        film, duration = render_remotion(job, root, first, lambda: None)
        manifest = json.loads((first / "manifest.json").read_text())
        assert manifest["scenes"][0]["caption_layout"]
        assert any(len(c["lines"]) == 2 for c in manifest["scenes"][0]["caption_layout"])
        shutil.copyfile(film, output / "fixture.mp4")
        shutil.copyfile(first / "manifest.json", output / "fixture-manifest.json")
        shutil.copyfile(first / "subtitles.srt", output / "fixture-subtitles.srt")
        for frame in [0, 15, 45, 59]:
            run_checked(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-i",
                    str(film),
                    "-vf",
                    f"select=eq(n\\,{frame})",
                    "-frames:v",
                    "1",
                    "-update",
                    "1",
                    str(output / f"frame-{frame:03d}.png"),
                ]
            )
        second = root / "render-2"
        second.mkdir()
        render_remotion(job, root, second, lambda: None)
        repeat = json.loads((second / "manifest.json").read_text())
        assert repeat["cache"] == {"hits": 1, "rendered": 0, "total": 1}
        previews = style_previews({"id": "fixture-preview", **snap}, root, rec)
        for path in (root / "previews" / "fixture-preview").rglob("*.png"):
            if path.parent.name != "public":
                shutil.copyfile(path, output / ("preview-" + path.name))
        info = probe(film)
        result = {
            "fixture_only": True,
            "source_media": "local synthetic geometric image; silent WAV",
            "live_calls": 0,
            "duration": duration,
            "cache_repeat": repeat["cache"],
            "previews": list(previews),
            "streams": [
                {
                    "codec_type": s["codec_type"],
                    "codec_name": s["codec_name"],
                    "width": s.get("width"),
                    "height": s.get("height"),
                    "nb_frames": s.get("nb_frames"),
                }
                for s in info["streams"]
            ],
            "caption_layout": manifest["scenes"][0]["caption_layout"],
        }
        (output / "acceptance.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
