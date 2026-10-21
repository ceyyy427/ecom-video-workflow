"""Isolated customer visual retake after category voice acceptance. No provider calls."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from fastapi.testclient import TestClient

    from ecom_video.api import create_app
    from ecom_video.media import digest, safe_path
    from ecom_video.worker import Worker

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, required=True)
    data = ap.parse_args().data.resolve()
    assert not data.is_relative_to(ROOT)
    receipt = json.loads((data / "versions.json").read_text())
    root = data / "runtime"
    c = TestClient(create_app(root), base_url="http://localhost")
    c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]
    base = "/api/customer-projects/" + receipt["project_id"]
    parent = c.get("/api/jobs/" + receipt["revised"]).json()
    p = c.get(base).json()

    def version(p):
        return {
            "revision": p["revision"],
            "job_id": p["job"]["id"],
            "board_revision": p["job"]["storyboard_revision"],
        }

    if p["job"]["id"] == parent["id"]:
        response = c.post(
            base + "/revise-shot",
            json={
                **version(p),
                "shot_id": parent["storyboard"]["shots"][0]["shot_id"],
                "request_id": "production-visual-retake-0001",
                "changes": {
                    "motion_plan": {
                        **parent["storyboard"]["shots"][0]["motion_plan"],
                        "cue_offset": 0.25,
                        "strength": "subtle",
                    }
                },
            },
        )
        assert response.is_success, response.text
        p = response.json()
    assert p["job"]["parent_id"] == parent["id"]
    if p["job"]["status"] == "draft":
        response = c.post(base + "/submit", json=version(p))
        assert response.is_success, response.text
        p = response.json()
    if p["job"]["status"] == "queued":
        assert Worker(root).run_once()
    p = c.get(base).json()
    child = p["job"]
    assert child["status"] == "needs_review" and not child["reviews"]
    assert c.get("/api/jobs/" + parent["id"]).json() == parent

    def directory(job):
        return safe_path(
            root, next(a["path"] for a in job["artifacts"] if a["kind"] == "video")
        ).parent

    before, after = directory(parent), directory(child)
    m, n = [json.loads((d / "manifest.json").read_text()) for d in (before, after)]
    count = len(n["scenes"])
    assert n["cache"] == {"hits": count - 1, "rendered": 1, "total": count}
    for i in range(1, count):
        assert m["scenes"][i]["cache_key"] == n["scenes"][i]["cache_key"]
        assert digest(before / f"scene-{i:03d}.mp4") == digest(after / f"scene-{i:03d}.mp4")
    assert digest(before / "narration.wav") == digest(after / "narration.wav")
    assert {k: v for k, v in m["alignment"].items() if k != "inherited_from_alignment_id"} == {
        k: v for k, v in n["alignment"].items() if k != "inherited_from_alignment_id"
    }
    for source, dest in (
        ("output.mp4", "visual-video.mp4"),
        ("manifest.json", "visual-manifest.json"),
        ("shotbook.json", "visual-shotbook.json"),
    ):
        (data / "deliverables" / dest).write_bytes((after / source).read_bytes())
    (data / "visual.json").write_text(
        json.dumps(
            {
                "parent": parent["id"],
                "child": child["id"],
                "cache": n["cache"],
                "other_scene_files_unchanged": True,
                "narration_and_alignment_unchanged": True,
                "production": child["storyboard"]["creative"]["production"],
                "film_sha256": digest(after / "output.mp4"),
                "status": "needs_review",
                "provider_calls": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print("Actual customer first-shot revision: one render, other scene files/narration unchanged")


if __name__ == "__main__":
    main()
