import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from ecom_video.vision_model import generate, identity

ROOT = Path(__file__).resolve().parents[1]
ref = ROOT / "examples/p10-real/opening/reference.jpg"
files = [
    ROOT / "var/analyses/e4d97c4912494e849afd97a07b0eaaf4/motion-clip-00-05.jpg",
    ROOT / "var/analyses/b014010de769434f9b6c661f87eeec43/00-0.jpg",
]
schema = {
    "type": "object",
    "properties": {
        k: {"type": "boolean"} for k in ["same_visible_design", "different_visible_design"]
    },
    "required": ["same_visible_design", "different_visible_design"],
    "additionalProperties": False,
}
results = []
model = identity()
for i, f in enumerate(files):
    canvas = Image.new("RGB", (1024, 540), "white")
    draw = ImageDraw.Draw(canvas)
    for n, source in enumerate([ref, f]):
        with Image.open(source) as im:
            im = ImageOps.contain(im.convert("RGB"), (512, 512))
            canvas.paste(im, (n * 512 + (512 - im.width) // 2, 28 + (512 - im.height) // 2))
        draw.text((n * 512 + 10, 8), "REFERENCE A" if n == 0 else "CANDIDATE B", fill="black")
    image = ROOT / f"docs/evidence/p10/identity-probe-{i}.jpg"
    canvas.save(image)
    r = generate(
        "Compare the product in left panel A with the corresponding product in right panel B. Compare visible color, silhouette, neck, handle and lid design. Is the same product design clearly visible? Or a visibly different design? Opening a cap does not change its design. Ignore people, background and liquid. Do not confuse the receiving cup with the pouring bottle. Answer both false if hidden or ambiguous. Return two booleans only.",
        schema,
        [image],
        model,
    )
    results.append({"input": str(image), "result": r})
    print(results[-1], flush=True)
    (ROOT / "docs/evidence/p10/identity-probe.json").write_text(json.dumps(results, indent=2))
