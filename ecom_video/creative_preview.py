"""Bounded silent previews of current, unconfirmed proposals in the existing renderer."""

import json
import shutil
import uuid
from pathlib import Path

from .creative import signature
from .delivery_plan import identity_matches
from .media import digest, inspect_media, run_checked, safe_path
from .renderer import write_json
from .resource_leases import Lease


def preview_typography(props, has_fact):
    from .subtitle_layout import layout_captions
    from .visual_finish import caption_color, prepare_visuals

    # Muted planning previews show the complete sentence even for pure showcases.
    # A short title must never become a claim with its conditions removed.
    display = {**props, "headline": "" if has_fact else props["text"], "format": "narrated"}
    visuals = prepare_visuals(display)
    if has_fact:
        visuals["captions"] = layout_captions(
            [{"text": props["text"], "start": 0, "end": 3}],
            props["brand"]["subtitle_size"],
            caption_color(display),
        )
    return {**display, **visuals}


def guarded_motion(candidate, index, decision):
    from .semantic_mix import guard_decision

    return guard_decision(
        {
            "script": "\n".join(s["text"] for s in candidate["payload"]),
            "provenance": {"facts": candidate["source_facts"], "scenes": candidate["payload"]},
        },
        index,
        decision,
    )


def preview_specs(p, candidate):
    from .prompt_catalog import usable_media

    assets = [
        a
        for a in p["media"]
        if a["kind"] != "audio"
        and (
            not p["settings"].get("delivery_version")
            or identity_matches(a, p["settings"].get("identity_lock"))
        )
    ]
    if not assets:
        raise ValueError("缺少符合款式/配色限制的素材，请上传并人工核对")
    second = next(
        (
            i
            for i, v in enumerate(candidate["visual_plan"])
            if i and v["kind"] != "action" and candidate["payload"][i].get("fact_ids")
        ),
        None,
    )
    if second is None:
        raise ValueError("尚无可安全预览的说明段；动作须在完整成片检查，请补说明素材或逐镜安排")
    result = []
    for index in (0, second):
        visual = candidate["visual_plan"][index]
        eligible = [
            a
            for a in assets
            if a["kind"] == "image"
            or a.get("source_in", 0) + 3 <= a["metadata"]["duration"] + 0.001
        ]
        if not eligible:
            raise ValueError("动态预览需要至少3秒连续画面或商品图，请调整入点/补素材")
        wanted = "detail" if visual["kind"] == "detail" else "product"
        asset = max(
            eligible,
            key=lambda a: (
                a["kind"] == "video",
                a.get("role") == wanted,
                a.get("role") != "evidence",
            ),
        )
        result.append(
            {
                "asset": asset,
                "source_in": asset.get("source_in", 0),
                "seconds": 3,
                "line": index,
                "card": visual.get("card") if usable_media(asset) else None,
                "basis": "素材用途候选，未证明讲解对应性；无声/估算节奏，需人工回看"
                + ("；清晰度不足，与正式生产一致关闭卡片" if not usable_media(asset) else ""),
            }
        )
    return result


def preview_path(root, pid, key):
    import re

    if not re.fullmatch(r"[a-f0-9]{64}", key):
        raise KeyError(key)
    folder = safe_path(root, f"previews/joint-{pid}/{key}")
    path = folder / "preview.mp4"
    if not path.is_file() or not (folder / "manifest.json").is_file():
        raise KeyError(key)
    meta = json.loads((folder / "manifest.json").read_text())
    if digest(path) != meta["sha256"]:
        raise ValueError("预览文件已变化，请重新生成")
    return path


def create_preview(root, store, p, candidate, basis):
    from .remotion_renderer import ENGINE, engine_hash, prepare_source_video
    from .shotcraft import MotionPlan, resolve_motion

    specs = preview_specs(p, candidate)
    for spec in specs:
        asset = spec["asset"]
        if digest(safe_path(root, asset["path"])) != asset["sha256"]:
            raise ValueError("原素材已变化，请重新上传并核对")
    key = signature(
        {
            "version": 1,
            "basis": basis,
            "candidate": candidate,
            "engine": engine_hash(),
            "preview_code": digest(Path(__file__)),
        }
    )
    parent = Path(root) / "previews" / ("joint-" + p["id"])
    folder = parent / key
    url = f"/api/customer-projects/{p['id']}/creative-proposals/previews/{key}"
    response = {
        "key": key,
        "url": url,
        "duration": 6,
        "muted": True,
        "approval": "none",
        "width": 360,
        "height": 640,
        "note": "6秒无声排版与动效示意，素材内容/时刻待人工核对；不是实际配音节奏或成片签收",
    }
    with Lease(store) as lease:
        if folder.exists():
            preview_path(root, p["id"], key)
            return {**response, "cache_hit": True}
        parent.mkdir(parents=True, exist_ok=True)
        temp = parent / (".building-" + uuid.uuid4().hex)
        public = temp / "public"
        public.mkdir(parents=True)
        try:
            shots = []
            for i, spec in enumerate(specs):
                asset = spec["asset"]
                src = safe_path(root, asset["path"])
                filename = (
                    f"source-{i}.mp4" if asset["kind"] == "video" else f"source-{i}" + src.suffix
                )
                if asset["kind"] == "video":
                    prepare_source_video(
                        src,
                        public / filename,
                        {
                            "source_in": spec["source_in"],
                            "duration": 3,
                            "frames": 90,
                            "source_framing": "original",
                            "focus_x": 0.5,
                            "focus_y": 0.5,
                        },
                        lease.check,
                    )
                else:
                    shutil.copy2(src, public / filename)
                style = candidate["direction"]
                text = candidate["payload"][spec["line"]]["text"]
                card = spec["card"]
                props = {
                    "src": filename,
                    "kind": asset["kind"],
                    "frames": 90,
                    "text": text,
                    "headline": text[:8],
                    "style": style["id"],
                    "brand": {
                        "name": "创意预览 · 未确认",
                        "paper": style["colors"][0],
                        "ink": style["colors"][1],
                        "accent": style["colors"][2],
                        "subtitle_size": 60,
                    },
                    "format": p["settings"]["brief"]["format"],
                    "treatment": "footage" if asset["kind"] == "video" else "hero",
                    "transition": "cut",
                    "motion": "static" if asset["kind"] == "video" else "push",
                    "fit": "contain",
                    "focus_x": 0.5,
                    "focus_y": 0.5,
                    "sample": False,
                    "preview": True,
                    "words": [],
                    "voiceStart": 0,
                    "voiceEnd": 3,
                    "index": i + 1,
                    "count": 2,
                    "role": asset.get("role", "product"),
                }
                plan = MotionPlan(
                    prompt_card=card["id"] if card else None,
                    visual_finish="polished-v1",
                    intent="hook" if not i else "detail",
                ).model_dump()
                decision = resolve_motion(
                    {
                        "frames": 90,
                        "text": text,
                        "headline": props["headline"],
                        "shot_recipe": card["recipe"] if card else "none",
                        "motion_plan": plan,
                    },
                    [],
                )
                decision = guarded_motion(candidate, spec["line"], decision)
                if decision.get("suppress_headline"):
                    props["headline"] = ""
                props.update(shotRecipe=decision["recipe"], motionPlan=decision)
                props.update(
                    preview_typography(props, bool(candidate["payload"][spec["line"]]["fact_ids"]))
                )
                shots.append({"key": f"part-{i}", "props": props})
            config = temp / "input.json"
            write_json(
                config,
                {
                    "mode": "preview",
                    "publicDir": str(public.resolve()),
                    "outputDir": str(temp.resolve()),
                    "shots": shots,
                },
            )
            run_checked(
                ["node", str(ENGINE / "render.mjs"), str(config.resolve())],
                check=lease.check,
                timeout=150,
            )
            listing = temp / "concat.txt"
            listing.write_text("file 'part-0.mp4'\nfile 'part-1.mp4'\n")
            output = temp / "preview.mp4"
            run_checked(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(listing),
                    "-c",
                    "copy",
                    "-movflags",
                    "+faststart",
                    str(output),
                ],
                check=lease.check,
                timeout=30,
            )
            meta = inspect_media(output, "video")
            if (
                output.stat().st_size > 20 * 1024**2
                or abs(meta["duration"] - 6) > 0.05
                or meta["width"] != 360
                or meta["height"] != 640
            ):
                raise ValueError("预览超出时长/分辨率/体积预算")
            run_checked(
                ["ffmpeg", "-v", "error", "-xerror", "-i", str(output), "-f", "null", "-"],
                check=lease.check,
                timeout=30,
            )
            for spec in specs:
                if digest(safe_path(root, spec["asset"]["path"])) != spec["asset"]["sha256"]:
                    raise ValueError("预览期间素材发生变化，请重新上传核对")
            write_json(
                temp / "manifest.json",
                {
                    **response,
                    "sha256": digest(output),
                    "basis": basis,
                    "sources": [
                        {
                            "sha256": s["asset"]["sha256"],
                            "source_in": s["source_in"],
                            "line": s["line"],
                            "basis": s["basis"],
                        }
                        for s in specs
                    ],
                },
            )
            shutil.rmtree(public)
            for name in (
                "part-0.mp4",
                "part-1.mp4",
                "part-0.png",
                "part-1.png",
                "input.json",
                "concat.txt",
            ):
                (temp / name).unlink(missing_ok=True)
            # Bound disposable preview history; production versions/artifacts are never touched.
            old = sorted(
                (d for d in parent.iterdir() if d.is_dir() and not d.name.startswith(".")),
                key=lambda d: d.stat().st_mtime,
            )
            for directory in old[:-5]:
                shutil.rmtree(directory)
            lease.check()
            temp.rename(folder)
        finally:
            if temp.exists():
                shutil.rmtree(temp)
    return {**response, "cache_hit": False}
