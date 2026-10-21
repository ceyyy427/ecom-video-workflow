import json
from pathlib import Path

from ecom_video.product_inspection import appearance, motion_state, reference_subject
from ecom_video.vision_model import identity

root = Path(__file__).resolve().parents[1]
model = identity()
out = root / "docs/evidence/p10" / ("split-" + model["model"].split(":")[-1] + ".json")
results = []
ref = root / "examples/p10-real/opening/reference.jpg"
category = reference_subject(ref, model)
print("CATEGORY",category,flush=True)
for file in [
    "var/analyses/e4d97c4912494e849afd97a07b0eaaf4/motion-clip-00-00.jpg",
    "var/analyses/e4d97c4912494e849afd97a07b0eaaf4/motion-clip-00-05.jpg",
    "docs/evidence/p10/negative-pour.jpg",
]:
    frame = root / file
    match=appearance(ref, frame, model, category)
    print("MATCH",file,match,flush=True)
    r = {
        "model": model,
        "file": file,
        "match": match,
        "motion": motion_state(frame, model, category),
    }
    print(r, flush=True)
    results.append(r)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2))
