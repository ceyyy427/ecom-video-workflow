"""Read-only HTTP and static markup acceptance. No browser or Computer Use."""

import hashlib
import json
import subprocess
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]


def main():
    files = {
        "video": "output.mp4",
        "parent": "parent.mp4",
        "retake": "retake.mp4",
        "poster": "poster.jpg",
        "narration": "narration.wav",
        "shotbook": "shotbook.json",
        "subtitles": "subtitles.srt",
        "recommendations": "recommendations.json",
        "treatment": "treatment.json",
        "selection": "manual-selection.json",
    }
    receipts = []
    with httpx.Client(base_url="http://127.0.0.1:8765", trust_env=False, timeout=60) as client:
        rows = client.get("/api/samples/refinement").json()
        assert {r["style"] for r in rows} == {"headphones", "serum"}
        assert all(
            r["status"] == "needs_review" and "listening" in r["review_required"] for r in rows
        )
        for row in rows:
            case = row["style"]
            base = "/api/samples/refinement/" + case
            for kind, name in files.items():
                response = client.get(base + "/" + kind + "?download=true")
                assert (
                    response.status_code == 200
                    and "attachment" in response.headers["content-disposition"]
                )
                local = ROOT / "examples/refinement-demo" / case / name
                assert (
                    hashlib.sha256(response.content).digest()
                    == hashlib.sha256(local.read_bytes()).digest()
                )
                receipts.append({"case": case, "kind": kind, "http": 200, "sha_equal": True})
            assert client.get(base + "/source").status_code == 404
            for kind in ["video", "parent", "retake"]:
                response = client.get(base + "/" + kind, headers={"Range": "bytes=0-1023"})
                assert response.status_code == 206 and len(response.content) == 1024
        response = client.get("/samples")
        assert response.status_code == 200
        dom = BeautifulSoup(response.text, "html.parser")
        assert len(dom.select("#refinementExamples #refinementGallery")) == 1
        assert "人工" in dom.select_one("#refinementExamples").get_text()
        for name in ["samples", "customer"]:
            response = client.get("/static/" + name + ".js")
            assert response.status_code == 200
            subprocess.run(
                ["node", "--check", str(ROOT / "ecom_video/web" / (name + ".js"))], check=True
            )
        assert len(client.get("/api/samples/quality").json()) == 3
    record = {
        "files": receipts,
        "range_responses": 6,
        "source_endpoints": "404",
        "static_markup_and_js_checked": True,
        "browser_ui_checked": False,
        "computer_use": False,
        "business_writes": 0,
        "human_review": "pending",
    }
    (ROOT / "docs/evidence/huashu-category/http.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2)
    )
    print(
        "20 download SHA checks, 6 Range requests, static markup/JS and legacy gallery passed; no browser/UI actions"
    )


if __name__ == "__main__":
    main()
