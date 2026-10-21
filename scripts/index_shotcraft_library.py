"""Compile an already downloaded, pinned Apache-2.0 reference snapshot; never execute it."""

import argparse
import hashlib
import json
from pathlib import Path


def compile_index(snapshot):
    meta = json.loads((snapshot / "snapshot.json").read_text())
    raw = json.loads((snapshot / "gallery/api/library.json").read_text())
    cards = []
    for c in raw["cards"]:
        path = c["source"]
        source = snapshot / path
        assert source.resolve().is_relative_to(snapshot.resolve())
        body = source.read_text()
        sha = hashlib.sha256(source.read_bytes()).hexdigest()
        assert sha == meta["files"][path]["sha256"]
        code = [
            {"path": p, **v}
            for p, v in meta["files"].items()
            if p.startswith("demos/") and "/" + c["name"] + "/" in p and p.endswith((".ts", ".tsx"))
        ]
        assert code
        styles = []
        for style in c["styles"]:
            media = style.get("media", {})
            assert media.get("type") == "mp4" and media["url"].startswith("./media/")
            styles.append(
                {
                    **{k: v for k, v in style.items() if k != "media"},
                    "sample_url": "https://vincentwei1021.github.io/video-shotcraft/"
                    + media["url"][2:],
                }
            )
        cards.append(
            {
                **{k: v for k, v in c.items() if k not in ("styles", "sourceUrl")},
                "id": c["name"],
                "styles": styles,
                "body": body,
                "body_sha256": sha,
                "implementation_sources": code,
                "source_url": meta["files"][path]["url"],
            }
        )
    assert len(cards) == 124 and sum(len(c["styles"]) for c in cards) == 150
    return {
        "version": 1,
        "repository": meta["repository"],
        "commit": meta["commit"],
        "license": meta["license"],
        "stats": raw["stats"],
        "categories": raw["categories"],
        "cards": cards,
        "sample_policy": "150 sample links indexed; preview videos/brand assets not downloaded or reused",
        "human_motion_review": "not_performed_for_all_150_samples",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--snapshot", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    data = compile_index(args.snapshot)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(hashlib.sha256(args.out.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
