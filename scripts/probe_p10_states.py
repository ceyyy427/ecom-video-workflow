import json
from pathlib import Path

from ecom_video.vision_model import generate, identity

ROOT = Path(__file__).resolve().parents[1]
folder = ROOT / "var/analyses/e4d97c4912494e849afd97a07b0eaaf4"
schema = {
    "type": "object",
    "properties": {
        "liquid_stream_outside_container": {"type": "boolean"},
        "cap_separated_from_mouth": {"type": "boolean"},
        "cap_covers_mouth": {"type": "boolean"},
        "hand_holds_cap": {"type": "boolean"},
    },
    "required": [
        "liquid_stream_outside_container",
        "cap_separated_from_mouth",
        "cap_covers_mouth",
        "hand_holds_cap",
    ],
    "additionalProperties": False,
}
model = identity()
results = []
for n in [0, 4, 5, 8, 11]:
    f = folder / f"motion-clip-00-{n:02d}.jpg"
    r = generate(
        "Inspect this single photograph. Answer each boolean about what is CLEARLY VISIBLE, not what might happen. A liquid stream means a continuous line of liquid OUTSIDE the container from its mouth; reflections, droplets on the wall, and liquid INSIDE do not count. A red neck ring is not a cap. No assumptions about motion. If hidden or uncertain answer false.",
        schema,
        [f],
        model,
    )
    results.append({"frame": f.name, "result": r})
    print(results[-1], flush=True)
    (ROOT / "docs/evidence/p10/state-probe.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2)
    )
