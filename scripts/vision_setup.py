"""Read-only local vision readiness check; install explicitly with Ollama's official CLI."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ecom_video.vision_model import identity  # noqa: E402

try:
    result = {"ready": True, **identity()}
except ValueError as exc:
    result = {"ready": False, "error": str(exc), "install_command": "ollama pull qwen3-vl:2b"}
print(json.dumps(result, ensure_ascii=False, indent=2))
raise SystemExit(0 if result["ready"] else 1)
