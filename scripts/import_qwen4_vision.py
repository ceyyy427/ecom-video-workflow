"""Import verified Qwen GGUF + projector through official local Ollama blob/create APIs.

Never overwrites an existing model with a different provenance or changes other models.
"""

import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.download_qwen4_vision import DEST, FILES, digest  # noqa: E402

MODEL = "ecom-qwen3vl:4b-q4km"
CONFIG = DEST.parent / "vision.json"


def main():
    manifest = json.loads((DEST / "source.json").read_text())
    for name, (size, sha) in FILES.items():
        path = DEST / name
        if not path.is_file() or path.stat().st_size != size or digest(path) != sha:
            raise ValueError("Model file failed verification: " + name)
    with httpx.Client(
        base_url="http://127.0.0.1:11434", timeout=180, trust_env=False, follow_redirects=False
    ) as c:
        tags = c.get("/api/tags")
        tags.raise_for_status()
        if any(m["name"] == MODEL for m in tags.json()["models"]):
            existing = c.post("/api/show", json={"model": MODEL})
            existing.raise_for_status()
            text = existing.json().get("modelfile", "")
            if not all(sha in text for _, sha in FILES.values()):
                raise ValueError(
                    "Existing model has different or unverifiable files; not overwritten"
                )
        else:
            for name, (size, sha) in FILES.items():
                endpoint = "/api/blobs/sha256:" + sha
                exists = c.head(endpoint)
                if exists.status_code == 404:
                    print("Importing local blob", name, flush=True)
                    with (DEST / name).open("rb") as f:
                        r = c.post(endpoint, content=f, headers={"Content-Length": str(size)})
                    r.raise_for_status()
                else:
                    exists.raise_for_status()
            payload = {
                "model": MODEL,
                "files": {n: "sha256:" + sha for n, (_, sha) in FILES.items()},
                "license": "Apache-2.0; official Qwen/Qwen3-VL-4B-Instruct-GGUF",
                "parameters": {"num_ctx": 8192, "temperature": 0},
                "stream": False,
            }
            r = c.post("/api/create", json=payload)
            r.raise_for_status()
            if r.json().get("status") != "success":
                raise ValueError("Ollama import failed: " + r.text[:500])
        show = c.post("/api/show", json={"model": MODEL})
        show.raise_for_status()
        details = show.json()
        if "vision" not in details.get("capabilities", []) or details.get("remote_host"):
            raise ValueError("Imported model is not local vision-capable")
        manifest.update(
            model=MODEL,
            ollama_version=c.get("/api/version").json()["version"],
            capabilities=details["capabilities"],
        )
        (DEST / "import.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        # Activate only after a genuine image inference and schema validation succeeds separately.
        print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
