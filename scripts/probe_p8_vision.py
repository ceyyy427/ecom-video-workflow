"""Real one-image schema probe; activates the installed model only after success."""

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ecom_video import vision_model  # noqa: E402
from scripts.import_qwen_vision import MODEL  # noqa: E402


def main():
    config = vision_model.CONFIG
    if config.is_file() and json.loads(config.read_text())["model"] != MODEL:
        raise ValueError("Existing project model setting differs; inspect before replacing")
    os.environ["ECOM_VISION_MODEL"] = MODEL
    model = vision_model.identity()
    image = ROOT / "docs/evidence/p8-live/source-frames/01-0.jpg"
    started = time.monotonic()
    result = vision_model.observe([image], model)
    record = {
        "model": model,
        "seconds": round(time.monotonic() - started, 2),
        "image": str(image),
        "observation": result,
        "real_model_call": True,
        "source_notice": "Generated fictional-product still, not customer footage",
    }
    (ROOT / "docs/evidence/p8-live/image-probe.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2)
    )
    temp = config.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps(
            {
                "model": MODEL,
                "source": "qwen3-vl-2b-official/source.json",
                "activation": "successful real image schema probe",
            },
            indent=2,
        )
    )
    temp.replace(config)
    print(json.dumps(record, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
