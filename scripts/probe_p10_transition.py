import json
from pathlib import Path
from typing import Literal

from ecom_video.creative import Strict
from ecom_video.vision_model import generate, identity


class Change(Strict):
    same_single_product: bool
    cap_moves_away_from_mouth: bool
    cap_moves_onto_mouth: bool
    hand_manipulates_cap: bool
    visible_before_and_after: bool
    uncertainty: Literal["none", "occlusion", "different_product", "unclear"]


p = Path("var/analyses/1ef86103989f41adb9d3926ccada9a8a")
prompt = "Two consecutive frames, first is BEFORE, second is AFTER. Compare the cap and mouth of the single bottle. Does the cap visibly move away from the mouth (opening), or onto it (closing)? A colored neck ring is NOT the cap. A stationary detached cap is not opening. Do not infer hidden motion. Hands may partly cover the cap, but the change must be visually clear in both frames. Output only booleans and uncertainty."
r = generate(
    prompt,
    Change.model_json_schema(),
    [p / "motion-clip-00-04.jpg", p / "motion-clip-00-05.jpg"],
    identity(),
    context_size=3072,
    max_tokens=256,
)
print(json.dumps(r))
Path("docs/evidence/p10/transition-probe.json").write_text(json.dumps(r, indent=2))
