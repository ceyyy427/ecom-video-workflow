"""Pure shot normalization shared by impact preview and immutable revisions."""

import copy


def apply_changes(shot, changes, selected=None, selected_id=None):
    changes = copy.deepcopy(changes)
    if selected:
        shot.update(
            asset_id=selected_id,
            role=selected["role"],
            evidence_note=selected["note"],
            source_in=selected["source_in"],
            motion="static" if selected["kind"] == "video" else "push",
        )
        if selected["kind"] != "video" and "source_framing" not in changes:
            shot["source_framing"] = "original"
    if changes.get("source_cuts"):
        shot["asset_id"] = changes["source_cuts"][0]["asset_id"]
    manual = isinstance(changes.get("motion_plan"), dict) and "windows" in changes["motion_plan"]
    if isinstance(changes.get("motion_plan"), dict):
        from .shotcraft import MotionPlan

        changes["motion_plan"] = MotionPlan.model_validate(
            {**(shot.get("motion_plan") or {}), **changes["motion_plan"]}
        ).model_dump()
    shot.update(changes)
    if (selected or "source_in" in changes) and shot.get("motion_plan"):
        shot["motion_plan"]["windows"] = [
            w
            for w in shot["motion_plan"]["windows"]
            if w.get("basis") == "voice_hint" or (manual and w.get("basis") == "manual")
        ]
