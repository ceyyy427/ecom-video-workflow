"""Opt-in delivery decisions: owned footage, declared identity and real source action ranges."""

import json
from typing import Literal

from pydantic import Field, model_validator

from .creative import Strict
from .shotcraft import MotionPlan


class IdentityTarget(Strict):
    sku: str = Field(min_length=1, max_length=80)
    color: str = Field(min_length=1, max_length=40)


class MediaIdentity(IdentityTarget):
    reviewer: str = Field(min_length=1, max_length=120)
    confirmed: Literal[True]


class CompleteAction(Strict):
    name: str = Field(min_length=1, max_length=40)
    start: float = Field(ge=0, le=600)
    end: float = Field(gt=0, le=600)

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("完整动作结束须晚于开始")
        return self


class SourceCut(Strict):
    asset_id: str = Field(min_length=1, max_length=64)
    source_in: float = Field(ge=0, le=600)
    source_duration: float = Field(ge=0.2, le=30)
    duration: float = Field(ge=0.2, le=15)
    reason: str = Field(default="", max_length=200)
    complete_action: CompleteAction | None = None


class Delivery(Strict):
    version: Literal[1] = 1
    caption_policy: Literal["pause-v1"] = "pause-v1"
    identity_lock: IdentityTarget | None = None


def meta(asset):
    value = asset["metadata"]
    return json.loads(value) if isinstance(value, str) else value


def identity_matches(asset, target):
    if not target:
        return True
    identity = meta(asset).get("identity") or {}
    return bool(
        identity.get("source_sha256") == asset["sha256"]
        and identity.get("reviewer", "").strip()
        and all(identity.get(k) == target[k] for k in ("sku", "color"))
    )


def identity_state(assets):
    return {a["id"]: meta(a).get("identity") for a in assets if a["kind"] != "audio"}


def validate_delivery(job, board):
    delivery = board.get("delivery")
    if not delivery and any(s.get("source_cuts") for s in board["shots"]):
        raise ValueError("多段实拍请先启用新版交付编排")
    if not delivery:
        return
    assets = {a["id"]: a for a in job["assets"]}
    for shot in board["shots"]:
        cuts = shot.get("source_cuts") or [
            {
                "asset_id": shot["asset_id"],
                "source_in": shot["source_in"],
                "source_duration": shot["duration"],
                "duration": shot["duration"],
            }
        ]
        if shot.get("source_cuts") and cuts[0]["asset_id"] != shot["asset_id"]:
            raise ValueError("第一段实拍须与本镜主素材一致")
        if (
            shot.get("source_cuts")
            and abs(cuts[0]["source_in"] - shot["source_in"]) > 1 / 60 + 0.000001
        ):
            raise ValueError("多段实拍请在分段编辑中修改第一段入点，不能只修改镜头入点")
        at = 0
        for cut in cuts:
            asset = assets.get(cut["asset_id"])
            if not asset or asset["kind"] == "audio":
                raise ValueError("选段必须属于本任务的画面素材")
            if not identity_matches(asset, delivery.get("identity_lock")):
                raise ValueError("款式或配色身份未知、与限制不符或声明已过期；请人工核对素材")
            if shot.get("source_cuts"):
                if asset["kind"] != "video":
                    raise ValueError("多段实拍仅支持视频")
                cut["duration"] = round(cut["duration"] * 30) / 30
                start, length = cut["source_in"], cut["source_duration"]
                if start + length > meta(asset)["duration"] + 0.001:
                    raise ValueError("实拍选段超出源素材")
                speed = length / cut["duration"]
                if not 0.5 <= speed <= 2:
                    raise ValueError("普通实拍速度须在0.5–2倍内；完整动作保持原速")
                from .idea_media import source_windows

                known_windows = source_windows(asset, start, length)
                if known_windows:
                    if abs(speed - 1) > 0.001:
                        raise ValueError("已知完整动作必须原速，不能用多段变速绕过保护")
                    known_plan = shot.get("motion_plan") or MotionPlan().model_dump()
                    if not known_plan["protect_action"]:
                        raise ValueError("已知完整动作不能关闭动作保护")
                    for window in known_windows:
                        shifted = {
                            **window,
                            "start": round(at + window["start"] / speed, 6),
                            "end": round(at + window["end"] / speed, 6),
                        }
                        if shifted not in known_plan["windows"]:
                            known_plan["windows"].append(shifted)
                    shot["motion_plan"] = MotionPlan.model_validate(known_plan).model_dump()
                action = cut.get("complete_action")
                if action:
                    if start > action["start"] + 0.001 or start + length < action["end"] - 0.001:
                        raise ValueError("选段会截断完整动作，请保留起止与收尾")
                    if abs(speed - 1) > 0.001:
                        raise ValueError("完整动作必须原速，不能用变速凑时长")
                    plan = shot.get("motion_plan") or MotionPlan().model_dump()
                    if not plan["protect_action"]:
                        raise ValueError("完整动作不能关闭动作保护")
                    window = {
                        "start": round(at + action["start"] - start, 6),
                        "end": round(at + action["end"] - start, 6),
                        "basis": "manual",
                    }
                    if window not in plan["windows"]:
                        plan["windows"].append(window)
                    shot["motion_plan"] = MotionPlan.model_validate(plan).model_dump()
            at += cut["duration"]
        if abs(at - shot["duration"]) > 0.001:
            raise ValueError("实拍各段总时长须精确覆盖本镜；不能循环或冻结填充")


def remap_cuts(board, mapping):
    for shot in board["shots"]:
        for cut in shot.get("source_cuts") or []:
            cut["asset_id"] = mapping.get(cut["asset_id"], cut["asset_id"])
