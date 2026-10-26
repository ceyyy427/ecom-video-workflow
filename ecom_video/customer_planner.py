"""Shot planning from measured media and optional constrained semantic proposals."""

import math
import re

from .clip_grounding import VERSION as GROUNDING_VERSION
from .creative import Brand, recommend_saved
from .production_direction import VERSION, choreography_for, direction_for, framing_for
from .shotcraft import effective_transitions, voice_guard
from .storyboard import default_board, validate_board


def plan_board(job, settings, style_id, alignment=None):
    from .creative_proposals import execution_plan
    from .semantic_mix import DETAIL
    from .spoken_copy import PREFIXES

    joint = execution_plan(job)
    rec = recommend_saved(job, settings["brief"])
    style = next((s for s in rec["options"] if s["id"] == style_id), None)
    if not style:
        raise ValueError("请选择本次推荐中的风格")
    direction = direction_for(style_id)
    board = default_board(job)
    lines = job["script"].splitlines()
    mode = settings["brief"]["format"]
    voice = next((a for a in job["assets"] if a["metadata"].get("customer_role") == "voice"), None)
    music = next((a for a in job["assets"] if a["metadata"].get("customer_role") == "music"), None)
    if mode != "showcase" and (not voice or not alignment or alignment["status"] != "confirmed"):
        raise ValueError("请上传与文稿一致的成品配音，并完成本机对齐与听核")
    if mode == "showcase":
        durations = [max(3, min(12, len(line) / 4)) for line in lines]
        if style_id == "cinema":
            durations[0] = max(5.4, durations[0])
    else:
        sentences = alignment["result"]["sentences"]
        if len(sentences) != len(lines):
            raise ValueError("对齐与当前脚本不一致")
        ends = (
            [0]
            + [round(s["start"] * 30) / 30 for s in sentences[1:]]
            + [math.ceil(voice["metadata"]["duration"] * 30) / 30]
        )
        durations = [round((b - a) * 30) / 30 for a, b in zip(ends, ends[1:], strict=False)]
    from .creative import idea_selection

    frozen = idea_selection(job)
    if (
        mode == "showcase"
        and frozen
        and frozen["option"]["native_style"] == style_id
        and lines == [s["text"] for s in frozen["option"]["scenes"]]
    ):
        durations = [s["seconds"] for s in frozen["option"]["scenes"]]
    # Match the renderer frame grid before allocating ranges, not after selecting them.
    durations = [round(t * 30) / 30 for t in durations]
    if any(not 1 <= t <= 15 for t in durations) or sum(durations) > 120:
        raise ValueError("每镜须为1–15秒、总长不超过120秒，请按语义拆分或合并文稿后重新确认")
    visuals = [a for a in job["assets"] if a["kind"] != "audio"]
    if settings.get("delivery_version"):
        from .delivery_plan import identity_matches

        board["delivery"] = {
            "version": 1,
            "caption_policy": "pause-v1",
            "identity_lock": settings.get("identity_lock"),
        }
        visuals = [a for a in visuals if identity_matches(a, settings.get("identity_lock"))]
    if not visuals:
        raise ValueError("请至少上传一份符合款式/配色限制并人工核对的商品画面")
    evidence = [
        a
        for a in visuals
        if a["kind"] == "video"
        and a["metadata"].get("customer_role") == "evidence"
        and a["metadata"].get("evidence_note")
    ]
    if mode == "review" and (not settings["review_context"].strip() or not evidence):
        raise ValueError("测评需要测试说明和标为证据的实拍视频，并填写来源说明")
    decisions = None
    if settings.get("auto_select"):
        from .clip_matching import select
        from .product_motion import voice_anchors

        constraints = {
            k: settings.get(k, False)
            for k in ("strict_product", "action_timing", "material_checks")
        }
        constraints["direction"] = {"version": VERSION, "style_id": style_id}
        if any(
            constraints[k] for k in ("strict_product", "action_timing", "material_checks")
        ) or settings.get("reference_only", False):
            reference = next(
                (
                    a
                    for a in visuals
                    if a["metadata"].get("library_id") == settings.get("product_reference_id")
                ),
                None,
            )
            if not reference or reference["kind"] != "image":
                raise ValueError("请选择本项目的商品参照图并重新识别")
            constraints["reference_sha256"] = reference["sha256"]
            constraints["reference_only"] = settings.get("reference_only", False)
        if constraints["action_timing"]:
            if mode == "showcase":
                raise ValueError("动作词对齐需要配音；纯展示请关闭动作对齐，仍可保留同款核对")
            constraints["anchors"] = voice_anchors(lines, durations, alignment)
        decisions, matching_model = select(
            {
                **job,
                "assets": visuals + [a for a in job["assets"] if a["kind"] == "audio"],
                "matching_constraints": constraints,
            },
            durations,
            mode,
        )
    counts = {a["id"]: 0 for a in visuals}
    notes = (
        [
            f"语义匹配模型：{matching_model['model']}；版本 {matching_model['digest']}；画面规则 {GROUNDING_VERSION}。识别与匹配仅供剪辑建议，不作为商品事实。"
        ]
        if decisions
        else []
    )
    notes.append(
        f"本次完整编排：{direction['structure']}；{direction['rhythm']}。自动选段{'开启' if decisions else '未开启：按素材用途建议，内容仍需人工安排'}。"
    )
    for i, (shot, line, duration) in enumerate(zip(board["shots"], lines, durations, strict=True)):
        target_framing = framing_for(style_id, line, i, len(lines))
        wanted = {"detail": "detail", "context": "lifestyle", "whole": "product"}[target_framing]
        must_evidence = mode == "review" and i == min(1, len(lines) - 1)
        if must_evidence:
            wanted = "evidence"
        eligible = [
            a
            for a in (evidence if must_evidence else visuals)
            if a["kind"] == "image"
            or a["metadata"].get("source_in", 0) + duration <= a["metadata"]["duration"] + 0.001
        ]
        if re.search("商品图|照片|图片|截图", line):
            images = [a for a in eligible if a["kind"] == "image"]
            if images:
                eligible = images
            else:
                notes.append(
                    f"第{i + 1}句要求图片，但尚无对应图片；保留实拍候选，需补图或人工调整，不能自动视为完成。"
                )
        if not eligible:
            raise ValueError(
                f"第{i + 1}镜需要{duration:.2f}秒画面，现有视频选段不足；请补充图片/更长视频或调整素材入点"
            )
        asset = max(
            eligible,
            key=lambda a: (
                100 * (a["metadata"].get("customer_role") == wanted)
                + 20 * (a["kind"] == "video")
                - 50 * counts[a["id"]]
            ),
        )
        if decisions:
            decision = decisions[i]
            asset = next(a for a in visuals if a["id"] == decision["asset_id"])
            grounding = decision["grounding"]
            context_note = ""
            if grounding["matched"]:
                context_note = (
                    "画面要求核对（关键帧观察，仍需人工复核）："
                    + "；".join(
                        f"{match['label']}←{match['term']}" for match in grounding["matched"]
                    )
                    + "。"
                )
            motion = decision.get("motion_check", {})
            if motion:
                context_note += f"整段参照外观：{motion['identity']}（抽样判断，非SKU鉴定）。"
                if decision.get("verified_range"):
                    span = decision["verified_range"]
                    context_note += f"仅使用连续确认一致的{span['start']:.2f}–{span['end']:.2f}s区间，其他部分不自动采用。"
            for action in decision.get("action_alignment", []):
                context_note += f"动作{action['kind']}：本镜配音词{action['voice_start']:.2f}–{action['voice_end']:.2f}s，画面动作证据{action['screen_start']:.2f}–{action['screen_end']:.2f}s。"
            notes.append(
                f"第{i + 1}镜：{asset['name']} {decision['start']:.2f}–{decision['start'] + duration:.2f}s；{decision['reason']}；编辑匹配分 {decision['score']}/3（非置信概率）。"
                + context_note
                + ("使用图片，未找到更合适的实拍段落。" if asset["kind"] == "image" else "")
                + ("片段重复，建议补充其他角度。" if decision["reused"] else "")
            )
            if decision.get("material_check"):
                check = decision["material_check"]
                notes.append(
                    f"第{i + 1}镜增强检查：参照绑定的主体可见候选；源区间重叠{check['overlap_seconds']:.2f}s；相似抽样{'需回看' if check['similar_frame_warning'] else '未命中'}，不是SKU或逐帧认证。"
                )
        if asset["metadata"].get("customer_role") != wanted and not decisions:
            notes.append(f"第{i + 1}镜没有合适的{wanted}角色素材，已用可用画面，请核对内容。")
        if counts[asset["id"]]:
            notes.append(f"第{i + 1}镜复用了{asset['name']}，可替换为不同角度。")
        counts[asset["id"]] += 1
        role = asset["metadata"].get("customer_role", "product")
        layout_role = role
        if decisions and role == "product":
            layout_role = {"detail": "detail", "context": "lifestyle"}.get(
                decisions[i]["observation"]["framing"], role
            )
        treatment = (
            "hero"
            if i == 0
            else "end"
            if i == len(lines) - 1
            else "macro"
            if layout_role == "detail"
            else "context"
            if layout_role == "lifestyle"
            else "split"
        )
        # Preserve the complete real video frame; do not replace filmed action with a graphic crop.
        if asset["kind"] == "video":
            treatment = "footage"
        headline_line = line
        if joint:
            for prefix in PREFIXES:
                if line.startswith(prefix):
                    headline_line = line[len(prefix) :]
                    break
        headline = next(
            (s.strip() for s in re.split("[，。！？；：]", headline_line) if s.strip()),
            headline_line,
        )
        if joint and len(headline) > 8:
            # Existing semantic labels are complete source substrings; never cut a noun.
            detail = DETAIL.search(headline)
            headline = detail.group() if detail else ""
        else:
            headline = headline[:8]
        shot.update(
            shot_id=f"shot-{i + 1:03d}",
            asset_id=asset["id"],
            duration=duration,
            source_in=(
                decisions[i]["start"] if decisions else asset["metadata"].get("source_in", 0)
            )
            if asset["kind"] == "video"
            else 0,
            motion="static" if asset["kind"] == "video" or i == len(lines) - 1 else "push",
            fit="contain",
            role=role,
            treatment=treatment,
            transition="wipe" if i == 1 else "cut",
            headline=headline,
            evidence_note=asset["metadata"].get("evidence_note", ""),
        )
    brand = (
        settings.get("brand")
        or Brand(
            name=settings["brand_name"] or job["title"][:24],
            paper=style["colors"][0],
            ink=style["colors"][1],
            accent=style["colors"][2],
        ).model_dump()
    )
    board.update(
        sample=False,
        creative_required=True,
        style=style["family"],
        music_id=music["id"] if music else None,
        music_db=-25,
    )
    board["narration"].update(
        mode="silent" if mode == "showcase" else "uploaded",
        asset_id=None if mode == "showcase" else voice["id"],
    )
    board["creative"] = {
        "production": VERSION,
        "brief": rec["brief"],
        "fingerprint": rec["fingerprint"],
        "style_id": style_id,
        "brand": brand,
        "alignment_id": alignment["id"] if mode != "showcase" else None,
        "sfx": settings["sfx"],
        "review_context": settings["review_context"],
    }
    for index, (shot, decision) in enumerate(
        zip(
            board["shots"],
            choreography_for(
                lines, style_id, durations, repeat_limit=settings.get("motion_repeat_limit", 2)
            ),
            strict=True,
        )
    ):
        shot.update(shot_recipe=decision["shot_recipe"], transition=decision["transition"])
        shot["motion_plan"] = decision["motion_plan"]
        if decisions:
            for action in decisions[index].get("complete_actions", []):
                shot["motion_plan"]["windows"].append(
                    {
                        "start": max(0, action["screen_start"]),
                        "end": min(shot["duration"], action["screen_end"]),
                        "basis": "analysis",
                    }
                )
            for action in decisions[index].get("action_alignment", [])[:8]:
                start = max(0, action["screen_start"])
                end = min(shot["duration"], action["screen_end"])
                if end > start:
                    shot["motion_plan"]["windows"].append(
                        {"start": start, "end": end, "basis": "analysis"}
                    )
        if not shot["motion_plan"]["windows"] and alignment:
            offset = sum(durations[:index])
            words = [
                {**w, "start": w["start"] - offset, "end": w["end"] - offset}
                for w in alignment["result"]["sentences"][index]["words"]
            ]
            shot["motion_plan"]["windows"] = voice_guard(lines[index], words, shot["duration"])
        notes.append(f"{shot['shot_id']} 动效建议：{decision['reason']}；可逐镜更换或关闭。")
    from .prompt_catalog import apply_prompts

    prompt_rows = apply_prompts(
        [
            {
                "shot_recipe": s["shot_recipe"],
                "transition": s["transition"],
                "motion_plan": s["motion_plan"],
                "reason": "",
            }
            for s in board["shots"]
        ],
        lines,
        durations,
        [next(a for a in visuals if a["id"] == s["asset_id"]) for s in board["shots"]],
        style["prompt_direction"],
        job=job,
    )
    for shot, row in zip(board["shots"], prompt_rows, strict=True):
        if row.get("clear_headline"):
            shot["headline"] = ""
        shot.update(
            shot_recipe=row["shot_recipe"],
            transition=row["transition"],
            motion_plan=row["motion_plan"],
        )
        notes.append(f"{shot['shot_id']} Prompt匹配：{row['reason']}；不新增商品事实。")
    from .idea_adoption import apply_board

    apply_board(job, board, mode, notes, preserve_media=decisions is not None)
    transitions = effective_transitions(
        [{**s, "frames": round(s["duration"] * 30)} for s in board["shots"]]
    )
    for shot, transition in zip(board["shots"], transitions, strict=True):
        if shot["transition"] != transition:
            notes.append(f"{shot['shot_id']}：动作保护区间靠近边界，入口改为直切。")
        shot["transition"] = transition
    return validate_board(job, board), notes
