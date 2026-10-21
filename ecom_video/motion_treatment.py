"""Local editorial adaptation of Huashu's rhythm/reading-window methods.

MIT reference: vendor/huashu-motion/SOURCES.json. No upstream runtime or prompts
are executed. These are planning hints, never product evidence or approvals.
"""

import copy

VERSION = "huashu-method-v1"
COMMIT = "3e927801e78b587878fb7dbb65d616326df00c21"
CALM = {"quiet", "cinema", "editorial"}
LIVELY = {"kinetic", "social", "collage", "bauhaus"}


def profile(style):
    calm, lively = style in CALM, style in LIVELY
    return {
        "version": VERSION,
        "language": "photo-led/editorial"
        if calm
        else "photo-led/kinetic-type"
        if lively
        else "photo-led/observation",
        "route": "continuous" if calm else "hybrid",
        "summary": (
            "实拍为主，轻落标题、细节留看、安静收尾；人工核对阅读与动作"
            if calm
            else "实拍为主，开头短促、中段一处强调、动作减弱、收尾留看；人工核对人声节奏"
            if lively
            else "实拍为主，一镜一个观察点，局部引导后停住阅读；人工核对焦点与依据"
        ),
        "source": {
            "repository": "alchaincyf/huashu-motion",
            "commit": COMMIT,
            "license": "MIT",
            "references": [
                "references/rhythm.md",
                "references/library/languages/photo-led.md",
                "references/verification.md",
            ],
        },
        "boundary": "不重写文稿、不加卖点、不为音乐节拍截断实拍动作；能量是编排意图，不是实测效果",
    }


def shape_rhythm(rows, style):
    """Only new planning: vary existing strength enums; keep words/voice/ranges intact."""
    result = copy.deepcopy(rows)
    safe = [
        i
        for i, r in enumerate(result)
        if 0 < i < len(result) - 1
        and r["motion_plan"]["intent"] != "action"
        and r["shot_recipe"] != "none"
    ]
    peak = min(safe, key=lambda i: abs(i - 0.55 * (len(result) - 1))) if safe else None
    for i, row in enumerate(result):
        plan = row["motion_plan"]
        if plan["intent"] == "action":
            row.update(shot_recipe="none", transition="cut")
            strength = "subtle"
        elif i == len(result) - 1:
            strength = "subtle"
        elif style in CALM:
            strength = "balanced" if i == peak else "subtle"
        else:
            strength = "bold" if i == peak or i == 0 and style in LIVELY else "balanced"
        plan["strength"] = strength
        row["reason"] += "；节奏：" + (
            "动作留看"
            if plan["intent"] == "action"
            else "收束留看"
            if i == len(result) - 1
            else "单处加强"
            if i == peak
            else "开场"
            if i == 0
            else "铺陈"
        )
    return result


def review_sheet(scenes, style):
    """Actual manifest cues and visibility estimates, not a subjective video grade."""
    shots = []
    for index, scene in enumerate(scenes):
        decision = scene.get("motion_decision")
        duration = scene["frames"] / 30
        emphasis = [
            {
                **c["emphasis"],
                "global_start": round(scene["start"] + c["emphasis"]["start"], 6),
                "global_end": round(scene["start"] + c["emphasis"]["end"], 6),
            }
            for c in scene.get("caption_layout", [])
            if c.get("emphasis")
        ]
        if not decision or (scene.get("motion_plan") or {}).get("visual_finish") != "polished-v1":
            shots.append(
                {
                    "shot_id": scene["shot_id"],
                    "motion": "legacy",
                    "emphasis": emphasis,
                    "warnings": [],
                }
            )
            continue
        cue = decision["cue_frame"] / 30
        settle = cue + (0 if decision["recipe"] == "none" else 0.4)
        entry_frames = {"push-stack": 13, "wipe": 12, "iris": 24}.get(
            scene.get("effective_transition"), 0
        )
        settle = max(settle, entry_frames / 30)
        exit_style = (
            scenes[index + 1].get("effective_transition") if index + 1 < len(scenes) else "cut"
        )
        exit_guard = {"push-stack": 14, "wipe": 12, "iris": 12}.get(exit_style, 0) / 30
        hold = round(max(0, duration - exit_guard - settle), 6)
        shots.append(
            {
                "shot_id": scene["shot_id"],
                "start": scene["start"],
                "end": scene["end"],
                "motion": decision["recipe"],
                "strength": decision["strength"],
                "cue_at": round(cue, 6),
                "title_settled_at": round(settle, 6),
                "title_settled_at_global": round(scene["start"] + settle, 6),
                "title_hold_seconds": hold,
                "guard_outcome": decision["guard_outcome"],
                "emphasis": emphasis,
                "warnings": ["short_title_hold"] if scene.get("headline") and hold < 0.6 else [],
            }
        )
    return {
        "version": VERSION,
        "direction": profile(style),
        "shots": shots,
        "cue_and_emphasis_time_basis": "shot_local_seconds",
        "scene_bounds_time_basis": "film_seconds",
        "energy_basis": "editorial_intent_not_measured_motion_or_effectiveness",
        "human_review": "pending",
        "coverage": "manifest_timing_only_not_visual_occlusion_or_human_listening",
    }
