"""Read-only, exact input audit for unchanged-model runtime benchmarks.

Does not certify model accuracy, cached embeddings or distinct model backends.
"""

import argparse
import json
from pathlib import Path


def compare(before, after):
    if not before or len(before) != len(after):
        raise ValueError("缺少实际请求；不能用空记录证明首次推理等价")
    images = 0
    for index, (a, b) in enumerate(zip(before, after, strict=True), 1):
        if a.get("measurement_valid") is not True or b.get("measurement_valid") is not True:
            raise ValueError("请求时钟无效")
        if (
            type(a.get("index")) is not int
            or type(b.get("index")) is not int
            or a["index"] != index
            or b["index"] != index
            or not isinstance(a.get("file"), str)
            or not a["file"]
            or a["file"] != b.get("file")
        ):
            raise ValueError("请求顺序或素材变化")
        if not a.get("payload") or json.dumps(
            a["payload"], sort_keys=True, allow_nan=False
        ) != json.dumps(b.get("payload"), sort_keys=True, allow_nan=False):
            raise ValueError("请求模型、图片SHA、提示词、schema或推理预算变化")
        images += sum(len(m.get("image_sha256", [])) for m in a["payload"].get("messages", []))
    return {"exact_request_inputs": True, "requests": len(before), "image_occurrences": images}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    args = parser.parse_args()
    report = compare(
        [json.loads(line) for line in args.before.read_text().splitlines()],
        [json.loads(line) for line in args.after.read_text().splitlines()],
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
