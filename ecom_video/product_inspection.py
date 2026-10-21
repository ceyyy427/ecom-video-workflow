"""Reference-bound, sampled visual states. This is appearance evidence, not SKU proof."""

import json
import os
from pathlib import Path
from typing import Annotated, Literal

from PIL import Image, ImageOps
from pydantic import Field

from .creative import Strict
from .inference_reuse import memoized
from .material_suitability import VERSION as MATERIAL_VERSION
from .media import digest, input_options, run_checked, safe_path
from .product_motion import VERSION, build_events, verified_ranges
from .vision_model import generate


def context_for(c, pid, *, required=True):
    row = c.execute("SELECT settings FROM customer_projects WHERE product_id=?", (pid,)).fetchone()
    settings = json.loads(row["settings"]) if row else {}
    if not (
        settings.get("strict_product")
        or settings.get("action_timing")
        or settings.get("material_checks")
    ):
        return {}
    ref = c.execute(
        "SELECT id,path,sha256,kind FROM customer_media WHERE id=? AND product_id=?",
        (settings.get("product_reference_id"), pid),
    ).fetchone()
    if not ref or ref["kind"] != "image":
        if required:
            raise ValueError("请先上传并选择一张清楚的商品参照图，再开始同款及动作识别")
        return {"reference_missing": True}
    return {
        "version": VERSION,
        "reference_id": ref["id"],
        "reference_path": ref["path"],
        "reference_sha256": ref["sha256"],
        "action_timing": bool(settings.get("action_timing")),
        **({"material_checks": MATERIAL_VERSION} if settings.get("material_checks") else {}),
    }


def current_context(analysis, context):
    result = analysis.get("result") or {}
    if result.get("context", {}) != context:
        return False
    if context.get("material_checks") and result.get("segments"):
        from .material_suitability import current_appearance

        return all(
            segment.get("quality", {}).get("blank")
            or current_appearance(
                {
                    "asset_sha256": result.get("source_sha256"),
                    "motion_check": segment.get("motion_check", {}),
                },
                context.get("reference_sha256"),
            )
            for segment in result["segments"]
        )
    return True


class ReferenceSubject(Strict):
    category: Literal["bottle", "cup", "other", "uncertain"]
    target_count: Literal["one", "multiple", "none", "uncertain"]


class Appearance(Strict):
    match: Literal["same", "different", "uncertain"]


class PermanentAppearance(Appearance):
    permanent_features: list[
        Literal[
            "rim_shape",
            "body_shape",
            "base_facets",
            "surface_relief",
            "surface_color",
            "handle_presence",
            "closure_structure",
            "interface_layout",
            "component_layout",
        ]
    ] = Field(max_length=5)
    uncertainty: Literal["none", "occlusion", "different_design", "ambiguous"]


class MotionFlags(Strict):
    target_count: Literal["one", "multiple", "none", "uncertain"]
    liquid_stream_outside_container: bool
    cap_separated_from_mouth: bool
    cap_covers_mouth: bool
    hand_holds_cap: bool


class VisibleMotionFlags(MotionFlags):
    visibility: Literal["full", "partial", "absent", "uncertain"]
    bbox: list[Annotated[int, Field(ge=0, le=1000)]] = Field(min_length=4, max_length=4)


@memoized
def reference_subject(reference, model):
    subject = ReferenceSubject.model_validate(
        generate(
            "Which is the single main product in this reference photo? bottle=container with narrower neck; cup=drinking vessel with wide mouth; other=another product. Multiple ambiguous main products=uncertain. Output enum only.",
            ReferenceSubject.model_json_schema(),
            [reference],
            model,
            context_size=3072,
            max_tokens=256,
        )
    )
    return subject.category if subject.target_count == "one" else "uncertain"


@memoized
def appearance(reference, frame, model, category="container", *, enhanced=False):
    if enhanced:
        result = PermanentAppearance.model_validate(
            generate(
                f"图1是参照商品，图2是实拍。只比较图1与图2中同类的单个主体，类别{category}。"
                + (
                    "杯子是饮用杯/玻璃杯，不要把背景中的咖啡壶、带把手的分享壶/水壶当成饮用杯或另一款杯子。"
                    if category == "cup"
                    else ""
                )
                + "液体增减或变色、空杯/满杯、手部握持、姿态和视角改变不代表换款。只核对外壁本身的颜色、轮廓、杯口、底部棱面、表面纹理/浮雕、部件布局、有无把手等永久结构。不要把液体颜色当作杯壁颜色。same需至少2个不同的清楚一致的永久特征，无可靠对应则uncertain；different只用于清楚矛盾的永久结构。permanent_features只列确实对应的特征，不猜品牌SKU。返回指定JSON。",
                PermanentAppearance.model_json_schema(),
                [reference, frame],
                model,
                context_size=3072,
                max_tokens=384,
            )
        ).model_dump()
        if result["match"] == "same" and (
            len(set(result["permanent_features"])) < 2 or result["uncertainty"] != "none"
        ):
            result["match"] = "uncertain"
        return result
    result = Appearance.model_validate(
        generate(
            f"图1为商品参照，主体类别{category}。图2为候选画面。比较两张图片里的主体外观，不要把不同图片里的对象当作同一画面中的多个对象。"
            "比较图1主体与图2同类主体的颜色、身形、可见结构；忽略背景、人、姿态和液体。不要把瓶子与杯子互相比较。"
            "match: same=可见外观一致，different=明显不同颜色或结构的另一款，uncertain=看不清或无法可靠区分。"
            "盖子打开不等于换款。仅返回JSON，不推断品牌SKU。",
            Appearance.model_json_schema(),
            [reference, frame],
            model,
            context_size=3072,
            max_tokens=256,
        )
    ).model_dump()
    return result


@memoized
def motion_state(frame, model, category="bottle", *, enhanced=False):
    schema = VisibleMotionFlags if enhanced else MotionFlags
    flags = schema.model_validate(
        generate(
            f"Inspect this single photograph, target category is {category}. Count ALL {category} objects first, including different designs; if multiple/none/unclear, do not attribute any action. Answer only about the UNIQUE {category}; ignore other categories. "
            + (
                "A cup is a drinking glass or mug; serving jugs/carafes/kettles/coffee pots are NOT cups and must not be counted as another cup. "
                if enhanced and category == "cup"
                else ""
            )
            + "A liquid stream must be a continuous line OUTSIDE the container FROM its mouth; reflections, surface droplets, liquid INSIDE do not count. "
            "Separated cap requires a visible AIR GAP between cap and mouth. Unscrewing while cap still touches the mouth counts as covers_mouth. "
            "The colored neck ring is not a cap. If no cap is visible, both cap flags are false. Hidden/unclear means false. "
            + (
                "For the unique target ONLY: visibility full=clear identifiable product, partial=recognizable but cropped/partly occluded, absent=not visible, uncertain=unrecognizable. bbox is the visible TARGET PRODUCT bounding box [left,top,right,bottom] in 0..1000 coordinates of THIS frame, excluding hands/background; never use the whole frame unless product fills it. No identifiable unique target => [0,0,0,0]. "
                if enhanced
                else ""
            )
            + "Output only JSON, no prose.",
            schema.model_json_schema(),
            [frame],
            model,
            context_size=3072,
            max_tokens=512 if enhanced else 256,
        )
    ).model_dump()
    if flags["target_count"] != "one":
        return {
            **({"visibility": flags["visibility"], "bbox": flags["bbox"]} if enhanced else {}),
            "flow": "unclear",
            "lid": "unclear",
            "handling_lid": False,
            "motion_flags": flags,
            "target_count": flags["target_count"],
        }
    covered, separated = flags["cap_covers_mouth"], flags["cap_separated_from_mouth"]
    return {
        **({"visibility": flags["visibility"], "bbox": flags["bbox"]} if enhanced else {}),
        "flow": "visible" if flags["liquid_stream_outside_container"] and not covered else "absent",
        "lid": "attached"
        if covered and not separated
        else "detached"
        if separated and not covered
        else "unclear",
        "handling_lid": flags["hand_holds_cap"],
        "motion_flags": flags,
        "target_count": flags["target_count"],
    }


def inspect_material_state(reference, frame, model, category, crop_budget, *, primary=None):
    """At most two target-crop rechecks per segment; raw primary judgment survives."""
    from .material_suitability import visible

    if category == "uncertain":
        return {
            "match": "uncertain",
            "flow": "unclear",
            "lid": "unclear",
            "handling_lid": False,
            "appearance_evidence": {
                "match": "uncertain",
                "permanent_features": [],
                "uncertainty": "ambiguous",
            },
        }
    if primary is None:
        primary = appearance(reference, frame, model, category, enhanced=True)
    else:
        reference_sha, frame_sha, primary = primary
        if digest(Path(reference)) != reference_sha or digest(Path(frame)) != frame_sha:
            raise ValueError("预取识别图片发生变化，请重试")
    match, proof = primary["match"], primary
    state = {"match": match, "flow": "unclear", "lid": "unclear", "handling_lid": False}
    # Clear conflicting structure remains a rejection. Weak full-frame judgments may
    # confuse a product with surrounding objects or the color of its contents.
    retry = (
        match != "same"
        and crop_budget[0] > 0
        and len(set(primary.get("permanent_features", []))) < 2
        and primary.get("uncertainty") != "different_design"
    )
    if match == "same" or retry:
        observed = motion_state(frame, model, category, enhanced=True)
        state.update(observed)
        if retry and visible({**observed, "match": "same"}):
            crop_budget[0] -= 1
            comparison = Path(frame).with_name(Path(frame).stem + "-target.jpg")
            with Image.open(frame) as im:
                w, h = im.size
                x1, y1, x2, y2 = observed["bbox"]
                im.crop(
                    (
                        max(0, round(x1 * w / 1000) - 8),
                        max(0, round(y1 * h / 1000) - 8),
                        min(w, round(x2 * w / 1000) + 8),
                        min(h, round(y2 * h / 1000) + 8),
                    )
                ).save(comparison)
            checked = appearance(reference, comparison, model, category, enhanced=True)
            proof = {
                **checked,
                "primary": primary,
                "method": "bounded_target_crop",
                "comparison_sha256": digest(comparison),
            }
            state["comparison_frame"] = comparison.name
            # The cropped comparison must independently meet the permanent-feature gate.
            match = checked["match"]
        if observed["target_count"] != "one":
            match = "uncertain"
    state.update(match=match, appearance_evidence=proof)
    return state


def primary_batches(frames, reference, model, category, check):
    """Serial groups of four share the native image-prefix KV; never skip a judgment.

    All requests still run independently, including when business caches are bypassed.
    Crop/motion processing remains chronological with its original two-crop budget.
    """
    while True:
        batch, terminal = [], False
        for _ in range(4):
            item = next(frames, None)
            if item is None:
                break
            check()
            i, t, frame, _ = item
            reference_sha, frame_sha = digest(Path(reference)), digest(Path(frame))
            primary = appearance(reference, frame, model, category, enhanced=True)
            if digest(Path(reference)) != reference_sha or digest(Path(frame)) != frame_sha:
                raise ValueError("预取识别图片发生变化，请重试")
            batch.append((i, t, frame, (reference_sha, frame_sha, primary)))
            terminal = primary["match"] == "different" and (
                len(set(primary["permanent_features"])) >= 2
                or primary["uncertainty"] == "different_design"
            )
            if terminal:
                break
        yield from batch
        if not batch or terminal:
            return


class CapTransition(Strict):
    same_single_product: bool
    cap_moves_away_from_mouth: bool
    cap_moves_onto_mouth: bool
    hand_manipulates_cap: bool
    visible_before_and_after: bool
    uncertainty: Literal["none", "occlusion", "different_product", "unclear"]


@memoized
def cap_observation(before, after, model, category):
    return CapTransition.model_validate(
        generate(
            f"Two consecutive frames, first is BEFORE, second is AFTER. Compare the cap and mouth of the single {category}. Does the cap visibly move away from the mouth (opening), or onto it (closing)? A colored neck ring is NOT the cap. A stationary detached cap is not opening. Do not infer hidden motion. Hands may partly cover the cap, but the change must be visually clear in both frames. Output only booleans and uncertainty.",
            CapTransition.model_json_schema(),
            [before, after],
            model,
            context_size=3072,
            max_tokens=256,
        )
    ).model_dump()


def temporal_lid_events(samples, folder, model, check, category="bottle"):
    """Resolve an ambiguous cap boundary from its two actual adjacent frames."""
    events, queries = [], 0
    for a, b in zip(samples, samples[1:], strict=False):
        if not (
            a["match"] == b["match"] == "same"
            and a.get("target_count") == b.get("target_count") == "one"
            and 0 < b["time"] - a["time"] <= 1.5
            and b["lid"] in ("attached", "detached")
            and (a["lid"] == "unclear" or a["lid"] != b["lid"])
            and (a["handling_lid"] or b["handling_lid"])
        ):
            continue
        if queries >= 8:
            break
        check()
        queries += 1
        result = cap_observation(
            Path(folder) / a["frame"], Path(folder) / b["frame"], model, category
        )
        opening, closing = result["cap_moves_away_from_mouth"], result["cap_moves_onto_mouth"]
        if not (
            result["same_single_product"]
            and result["hand_manipulates_cap"]
            and result["visible_before_and_after"]
            and result["uncertainty"] == "none"
            and opening != closing
            and b["lid"] == ("detached" if opening else "attached")
        ):
            continue
        events.append(
            {
                "kind": "open_lid" if opening else "close_lid",
                "start": a["time"],
                "end": b["time"],
                "anchor": (a["time"] + b["time"]) / 2,
                "evidence": "同款唯一主体相邻帧盖体位移复核",
                "temporal_observation": result,
            }
        )
    return events


def inspect_segment(root, source, kind, segment, folder, context, model, check, progress=None):
    reference = safe_path(root, context["reference_path"])
    if not reference.is_file() or digest(reference) != context["reference_sha256"]:
        raise ValueError("商品参照图缺失或变化，请重新上传")
    thumb = Path(folder) / "reference.jpg"
    with Image.open(reference) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((640, 640))
        im.save(thumb)
    cached_subject = Path(folder) / "reference-subject.json"
    if cached_subject.is_file():
        category = json.loads(cached_subject.read_text())["category"]
    else:
        category = reference_subject(thumb, model)
        cached_subject.write_text(
            json.dumps(
                {
                    "category": category,
                    "model": model,
                    "reference_sha256": context["reference_sha256"],
                }
            )
        )
    if kind == "image":
        times = [0.0]
    else:
        start, end = segment["start"], segment["end"]
        # Uniform measured sampling, up to 21 frames in a 15-second candidate.
        count = min(20, max(1, int((end - start) / 0.75)))
        times = [round(start + 0.05 + (end - start - 0.1) * i / count, 4) for i in range(count + 1)]
    samples = []
    crop_budget = [2]

    def frames():
        for i, t in enumerate(times):
            check()
            if progress:
                progress(f"核对外观与动作 {segment['id']} · 抽样 {i + 1}/{len(times)}")
            frame = Path(folder) / f"motion-{segment['id']}-{i:02d}.jpg"
            if kind == "image":
                with Image.open(source) as im:
                    im = ImageOps.exif_transpose(im).convert("RGB")
                    im.thumbnail((640, 640))
                    im.save(frame)
            else:
                run_checked(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-y",
                        *input_options(source),
                        "-ss",
                        str(t),
                        "-i",
                        str(source),
                        "-frames:v",
                        "1",
                        "-vf",
                        "scale=640:640:force_original_aspect_ratio=decrease",
                        str(frame),
                    ],
                    check,
                    timeout=30,
                )
            yield i, t, frame, None

    inputs = frames()
    if (
        kind == "video"
        and context.get("material_checks")
        and category != "uncertain"
        and os.getenv("ECOM_VISION_ACCELERATION", "auto") != "off"
    ):
        inputs = primary_batches(inputs, thumb, model, category, check)
    for _i, t, frame, primary in inputs:
        enhanced_state = None
        if kind == "image" and digest(source) == context["reference_sha256"]:
            match = "same"
        elif context.get("material_checks"):
            enhanced_state = inspect_material_state(
                thumb, frame, model, category, crop_budget, primary=primary
            )
            match = enhanced_state["match"]
        else:
            appearance_result = appearance(thumb, frame, model, category)
            match = appearance_result["match"]
        if category == "uncertain":
            match = "uncertain"
        state = {
            "match": match,
            "evidence": "参照图与当前帧的独立外观比较",
            "flow": "unclear",
            "lid": "unclear",
            "handling_lid": False,
        }
        if enhanced_state is not None:
            state.update(enhanced_state)
        if match == "same" and (
            context.get("material_checks")
            or not (kind == "image" and digest(source) == context["reference_sha256"])
        ):
            if enhanced_state is None:
                state.update(
                    motion_state(
                        frame, model, category, enhanced=bool(context.get("material_checks"))
                    )
                )
            if state["target_count"] != "one" or (
                context["action_timing"] and category not in ("bottle", "cup")
            ):
                state.update(match="uncertain", flow="unclear", lid="unclear", handling_lid=False)
        if context.get("material_checks"):
            from .material_suitability import frame_hash

            state["frame_hash"] = frame_hash(frame)
        samples.append({"time": t, "frame": frame.name, **state})
        # One definite different product is enough to reject the whole candidate.
        if match == "different":
            break
    matches = {s["match"] for s in samples}
    identity = (
        "different" if "different" in matches else "uncertain" if "uncertain" in matches else "same"
    )
    if digest(reference) != context["reference_sha256"]:
        raise ValueError("识别期间商品参照图变化，请重试")
    segment["motion_check"] = {
        **(
            {"material_checks_version": context["material_checks"]}
            if context.get("material_checks")
            else {}
        ),
        "version": VERSION,
        "reference_sha256": context["reference_sha256"],
        "identity": identity,
        "verified_ranges": verified_ranges(samples) if kind == "video" else [],
        "samples": samples,
        "events": [],
        "coverage": "sampled_not_sku_verification",
        "planned_samples": len(times),
        "reference_category": category,
    }
    if progress:
        progress(f"复核盖体变化 {segment['id']}")
    refine_segment(segment, folder, model, check, context)
    segment["frames"] += [s["frame"] for s in samples]
    segment["sample_times"] += [s["time"] for s in samples]
    for sample in samples:
        if sample.get("comparison_frame"):
            segment["frames"].append(sample["comparison_frame"])
            segment["sample_times"].append(sample["time"])


def refine_segment(segment, folder, model, check, context):
    """Reuse bound raw observations, but NEVER trust a prior inferred cap event."""
    motion = segment["motion_check"]
    samples = motion["samples"]
    events = []
    if context["action_timing"] or context.get("material_checks"):
        # Independent single-frame labels can contradict on an unchanged lid.
        # Every cap change requires explicit adjacent-frame displacement evidence.
        events = [e for e in build_events(samples) if e["kind"] == "pour"]
        if motion["reference_category"] in ("bottle", "cup"):
            events += temporal_lid_events(
                samples, folder, model, check, motion["reference_category"]
            )
    motion.update(
        version=VERSION,
        verified_ranges=verified_ranges(samples),
        events=sorted(events, key=lambda e: e["start"]),
    )
