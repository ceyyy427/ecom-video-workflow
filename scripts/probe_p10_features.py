import json
from pathlib import Path

from ecom_video.vision_model import generate, identity

ROOT = Path(__file__).resolve().parents[1]
fields = {
    "category": ["bottle", "cup", "other", "uncertain"],
    "body_color": [
        "colorless_transparent",
        "brown_transparent",
        "green_transparent",
        "opaque_white",
        "opaque_black",
        "metallic",
        "other",
        "uncertain",
    ],
    "cap_color": ["red", "black", "white", "metallic", "other", "not_visible", "uncertain"],
    "neck": ["long_narrow", "short_narrow", "wide_open", "uncertain"],
    "body_pattern": ["plain", "printed_or_labelled", "uncertain"],
}
schema = {
    "type": "object",
    "properties": {k: {"type": "string", "enum": v} for k, v in fields.items()},
    "required": list(fields),
    "additionalProperties": False,
}
files = [
    "examples/p10-real/opening/reference.jpg",
    "var/analyses/e4d97c4912494e849afd97a07b0eaaf4/motion-clip-00-00.jpg",
    "var/analyses/e4d97c4912494e849afd97a07b0eaaf4/motion-clip-00-05.jpg",
    "examples/p10-real/pouring/reference.jpg",
]
model = identity()
results = []
for f in files:
    r = generate(
        "Describe only visible appearance of the MAIN CONTAINER. If a bottle and a receiving cup are both shown, select the bottle. Ignore background/clothes/hand colors. body_color describes the visible container wall, NOT background or liquid. cap_color is the detachable cap, not neck ring; not_visible when cap absent/hidden. neck is silhouette: bottle has long_narrow or short_narrow neck, a cup has wide_open mouth. Do not infer material, brand or function. Choose uncertain when unclear. Output enum JSON only, no prose.",
        schema,
        [ROOT / f],
        model,
    )
    results.append({"file": f, "features": r})
    print(results[-1], flush=True)
    (ROOT / "docs/evidence/p10/feature-probe.json").write_text(json.dumps(results, indent=2))
