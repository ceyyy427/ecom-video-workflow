"""Independent manual event expectations never enter recognition or matching."""

import hashlib
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/evidence/p10"
delivery = ROOT / "examples/p10-real/outputs"
delivery.mkdir(exist_ok=True)
reports = []
licensed = {
    item["sha256"]: item
    for item in json.loads((ROOT / "examples/p10-real/sources.json").read_text())["sources"]
}
for name, kind, title in [
    ("opening", "open_lid", "红盖瓶-开盖对齐"),
    ("pouring-flask", "pour", "金属瓶-倒入对齐"),
]:
    folder = OUT / name
    p = json.loads((folder / "result.json").read_text())
    run = json.loads((folder / "run.json").read_text())
    source = next(a for a in p["media"] if a["name"] == "素材A.mp4")
    negative = next(a for a in p["media"] if a["name"] == "素材B.mp4")
    for asset in (source, negative):
        assert asset["sha256"] in licensed
        original = ROOT / licensed[asset["sha256"]]["local_path"]
        assert hashlib.sha256(original.read_bytes()).hexdigest() == asset["sha256"]
    checks = [s["motion_check"] for s in source["analysis"]["result"]["segments"]]
    assert all(m["version"] == "reference-motion-v4" for m in checks)
    events = [e for m in checks for e in m["events"]]
    assert all(
        s["motion_check"]["identity"] != "same" for s in negative["analysis"]["result"]["segments"]
    )
    assert all(
        not s["motion_check"].get("verified_ranges")
        for s in negative["analysis"]["result"]["segments"]
    ), "Wrong-product footage acquired a confirmed range"
    assert any(e["kind"] == kind for e in events)
    if name == "opening":
        assert not any(e["kind"] == "pour" for e in events), "Nonexistent pouring was hallucinated"
        assert any(abs(e["anchor"] - 3.625) <= 0.6 for e in events if e["kind"] == "open_lid"), (
            events
        )
    else:
        assert all(0.0 <= e["start"] < e["end"] <= 10.16 for e in events if e["kind"] == "pour"), (
            events
        )
    if name == "pouring-flask":
        assert not any(e["kind"] in ("open_lid", "close_lid") for e in events), (
            "Flask has no lid change"
        )
    assets = {a["id"]: a for a in p["job"]["assets"]}
    assert all(
        assets[s["asset_id"]]["kind"] == "video"
        and assets[s["asset_id"]]["sha256"] == source["sha256"]
        for s in p["job"]["storyboard"]["shots"]
    )
    # Independently reconstruct safe intervals; a rejected tail cannot invalidate
    # an earlier range, and no selected shot may cross an unknown/different frame.
    spans = []
    for m in checks:
        run_samples = []
        for sample in [*m["samples"], None]:
            valid = sample and sample["match"] == "same" and sample.get("target_count") == "one"
            if run_samples and (not valid or sample["time"] - run_samples[-1]["time"] > 1.5):
                if len(run_samples) >= 2:
                    spans.append((run_samples[0]["time"], run_samples[-1]["time"]))
                run_samples = []
            if valid:
                run_samples.append(sample)
    for shot in p["job"]["storyboard"]["shots"]:
        assert any(
            a - 1e-6 <= shot["source_in"] and shot["source_in"] + shot["duration"] <= b + 1e-6
            for a, b in spans
        ), (shot, spans)
    # This demo's first line contains exactly one known action token. Derive its
    # timing independently from the confirmed ASR, not from planning notes.
    assert p["alignment"]["status"] == "confirmed"
    words = p["alignment"]["result"]["sentences"][0]["words"]
    chars = [(ch, word) for word in words for ch in word["text"] if ch.isalnum()]
    token = "拧开瓶盖" if name == "opening" else "倒入"
    index = "".join(ch for ch, _ in chars).index(token)
    matched = chars[index : index + len(token)]
    assert all(word["anchored"] for _, word in matched)
    voice_start, voice_end = matched[0][1]["start"], matched[-1][1]["end"]
    source_in = p["job"]["storyboard"]["shots"][0]["source_in"]
    mapped_start, mapped_end = source_in + voice_start, source_in + voice_end
    compatible = [e for e in events if e["kind"] == kind]
    if kind == "pour":
        assert any(e["start"] <= mapped_start < mapped_end <= e["end"] for e in compatible)
        sync_error = None
    else:
        sync_error = min(abs(e["anchor"] - (mapped_start + mapped_end) / 2) for e in compatible)
        assert sync_error <= 0.6
    video = Path(run["video"])
    probe = json.loads(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(video)]
        )
    )
    duration = float(probe["format"]["duration"])
    (folder / "film-probe.json").write_text(json.dumps(probe, indent=2))
    with (folder / "decode.log").open("w") as f:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(video), "-f", "null", "-"], stderr=f, check=True
        )
    with (folder / "signal.log").open("w") as f:
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "info",
                "-i",
                str(video),
                "-af",
                "astats=metadata=0:reset=0",
                "-vf",
                "blackdetect=d=0.12:pix_th=0.05",
                "-f",
                "null",
                "-",
            ],
            stderr=f,
            check=True,
        )
    assert not (folder / "decode.log").read_text().strip()
    stream = next(s for s in probe["streams"] if s["codec_type"] == "video")
    assert (stream["width"], stream["height"], stream["r_frame_rate"]) == (1080, 1920, "30/1")
    assert any(s["codec_type"] == "audio" for s in probe["streams"])
    canvas = Image.new("RGB", (810, 1020), "#161616")
    draw = ImageDraw.Draw(canvas)
    for i, t in enumerate([duration * (i + 0.4) / 6 for i in range(6)]):
        frame = folder / f"film-{i}.jpg"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-ss",
                str(t),
                "-i",
                str(video),
                "-frames:v",
                "1",
                "-vf",
                "scale=270:480",
                str(frame),
            ],
            check=True,
        )
        x, y = i % 3 * 270, i // 3 * 510
        with Image.open(frame) as im:
            canvas.paste(im, (x, y))
        draw.text((x + 8, y + 486), f"{t:.2f}s", fill="white")
    canvas.save(folder / "film-contact.jpg")
    target = delivery / (title + ".mp4")
    shutil.copy2(video, target)
    reports.append(
        {
            "demo": name,
            "project_id": p["id"],
            "job_id": p["job"]["id"],
            "source_sha256": source["sha256"],
            "negative_source_sha256": negative["sha256"],
            "video": str(target.relative_to(ROOT)),
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "duration": duration,
            "actions": events,
            "motion_version": "reference-motion-v4",
            "reused_observations_from": source["analysis"]["result"].get(
                "reused_observations_from"
            ),
            "voice_action": {"token": token, "start": voice_start, "end": voice_end},
            "voice_mapped_source_interval": [mapped_start, mapped_end],
            "cap_center_error_seconds": sync_error,
            "all_video": True,
            "verified_source_intervals": spans,
            "selected_ranges": [
                {"start": shot["source_in"], "end": shot["source_in"] + shot["duration"]}
                for shot in p["job"]["storyboard"]["shots"]
            ],
            "planning_notes": p["planning_notes"],
            "wrong_product_excluded": True,
            "state": p["job"]["status"],
            "voice": "macOS Tingting local synthetic; NOT Volcengine; human listening pending",
        }
    )
before = json.loads((OUT / "before.json").read_text())
with sqlite3.connect(ROOT / "var/workflow.db") as c:
    jobs = {r[0] for r in c.execute("SELECT id FROM jobs")}
    counts = {
        t: c.execute("SELECT count(*) FROM " + t).fetchone()[0] for t in before["platform_counts"]
    }
assert set(before["jobs"]) <= jobs and counts == before["platform_counts"]
for path, sha in before["videos"].items():
    assert hashlib.sha256((ROOT / "var" / path).read_bytes()).hexdigest() == sha
report = {
    "demos": reports,
    "old_jobs_preserved": len(before["jobs"]),
    "old_films_preserved": len(before["videos"]),
    "platform_counts": counts,
    "human_review": "pending",
}
(OUT / "acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
(delivery / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps(report, ensure_ascii=False, indent=2))
