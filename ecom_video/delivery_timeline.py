"""Derived SHOTBOOK clock. Voice anchors are retained, never inferred here."""

from .creative import signature


def cut_records(scene, assets):
    cuts = scene.get("source_cuts") or [
        {
            "asset_id": scene["asset_id"],
            "source_in": scene["source_in"],
            "source_duration": scene["duration"],
            "duration": scene["duration"],
            "reason": "保留本镜已保存选段；请人工核对讲解对应性",
        }
    ]
    result, frame = [], 0
    for cut in cuts:
        asset = assets[cut["asset_id"]]
        frames = round(cut["duration"] * 30)
        result.append(
            {
                **cut,
                "asset_sha256": asset["sha256"],
                "source_name": asset["name"],
                "source_out": cut["source_in"] + cut["source_duration"],
                "scene_start_frame": frame,
                "scene_end_frame": frame + frames,
                "speed": cut["source_duration"] / cut["duration"],
            }
        )
        frame += frames
    return result


def timeline_record(snap, board, scenes, alignment):
    assets = {a["id"]: a for a in snap["assets"]}
    provenance = snap.get("provenance") or {}
    facts = provenance.get("scenes", [])
    rows = []
    for i, (scene, text) in enumerate(zip(scenes, snap["script"].splitlines(), strict=True)):
        words = alignment["sentences"][i]["words"] if alignment else []
        captions = [
            {
                "text": c["text"],
                "start": scene["start"] + c["start"],
                "end": scene["start"] + c["end"],
                "start_sample": round((scene["start"] + c["start"]) * 48000),
                "end_sample": round((scene["start"] + c["end"]) * 48000),
            }
            for c in scene.get("caption_layout", [])
        ]
        rows.append(
            {
                "shot_id": scene["shot_id"],
                "spoken_text": text,
                "fact_ids": facts[i].get("fact_ids", [])
                if i < len(facts) and facts[i].get("text") == text
                else [],
                "start_frame": round(scene["start"] * 30),
                "end_frame": round(scene["end"] * 30),
                "cuts": cut_records(scene, assets),
                "words": words,
                "captions": captions,
                "action_windows": (scene.get("motion_plan") or {}).get("windows", []),
                "motion": scene.get("motion_decision"),
                "basis": "已保存文稿/选段与原配音锚点；身份和动作声明仍需人工核对",
            }
        )
    voice = assets.get(board["narration"]["asset_id"])
    return {
        "version": 1,
        "fps": 30,
        "audio_sample_rate": 48000,
        "total_frames": sum(s["frames"] for s in scenes),
        "script_sha256": signature(snap["script"]),
        "voice_sha256": voice["sha256"] if voice else None,
        "alignment_sha256": signature(alignment) if alignment else None,
        "estimated_anchors_are_not_verified": True,
        **({"creative_plan": provenance["creative_plan"]} if provenance.get("creative_plan") else {}),
        "shots": rows,
    }
