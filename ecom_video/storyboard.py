"""Versioned, bounded edit decisions; no executable filters or paths in user input."""

import json
import shutil
import sys
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .creative import Creative, validate_creative
from .delivery_plan import Delivery, SourceCut, validate_delivery
from .shotcraft import MotionPlan, RecipeId
from .typography import Typography, validate_typography


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Shot(Strict):
    presentation: Literal["client", "legacy"] | None = None
    source_cuts: list[SourceCut] | None = Field(default=None, min_length=1, max_length=4)
    shot_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,48}$")
    headline: str = Field(default="", max_length=8)
    role: Literal["product", "detail", "lifestyle", "evidence"] = "product"
    treatment: Literal["auto", "hero", "macro", "split", "context", "end", "footage"] = "auto"
    transition: Literal["cut", "wipe", "iris", "push-stack", "line-carry", "media-pass"] = "cut"
    shot_recipe: RecipeId | None = None
    motion_plan: MotionPlan | None = None
    evidence_note: str = Field(default="", max_length=500)
    typography: Typography | None = None
    caption_note: str = Field(default="", max_length=40)
    asset_id: str | None = None
    duration: float = Field(default=3, ge=1, le=15)
    source_in: float = Field(default=0, ge=0, le=600)
    motion: Literal["static", "push", "pull", "pan_left", "pan_right"] = "static"
    fit: Literal["contain", "cover"] = "contain"
    source_framing: Literal["original", "square"] = "original"
    focus_x: float = Field(default=0.5, ge=0, le=1)
    focus_y: float = Field(default=0.5, ge=0, le=1)

    @model_validator(mode="after")
    def client_recipe_has_plan(self):
        if (
            self.presentation == "client"
            and self.shot_recipe not in (None, "none")
            and self.motion_plan is None
        ):
            raise ValueError("客户成片动效需要动效计划，请补齐声音与动作编排或保留历史样式")
        return self


class Narration(Strict):
    mode: Literal["silent", "uploaded", "local"] = "silent"
    asset_id: str | None = None
    rate: int = Field(default=210, ge=140, le=280)
    gain_db: float = Field(default=0, ge=-12, le=6)


class Board(Strict):
    delivery: Delivery | None = None
    version: Literal[1] = 1
    style: Literal["premium", "demo", "lifestyle"] = "premium"
    sample: bool = False
    creative: Creative | None = None
    creative_required: bool = False
    previous_creative: Creative | None = None
    shots: list[Shot] = Field(min_length=1, max_length=30)
    narration: Narration = Field(default_factory=Narration)
    music_id: str | None = None
    music_db: float = Field(default=-23, ge=-40, le=-10)


def metadata(asset):
    value = asset["metadata"]
    return json.loads(value) if isinstance(value, str) else value


def capabilities():
    return {
        "local_tts": sys.platform == "darwin" and bool(shutil.which("say")),
        "voice": "Tingting",
        "subtitle_alignment": "scene_level_not_word_aligned",
    }


def default_board(job):
    visuals = [a for a in job["assets"] if a["kind"] != "audio"]
    audio = next(
        (
            a
            for a in job["assets"]
            if a["kind"] == "audio" and metadata(a).get("customer_role") == "voice"
        ),
        next(
            (
                a
                for a in job["assets"]
                if a["kind"] == "audio" and not metadata(a).get("customer_role")
            ),
            None,
        ),
    )
    shots = []
    for i, _ in enumerate(job["script"].splitlines()):
        asset = visuals[i % len(visuals)] if visuals else None
        duration = job["seconds"]
        if asset and asset["kind"] == "video":
            duration = min(duration, max(1, int(metadata(asset)["duration"] * 30) / 30))
        shots.append(Shot(asset_id=asset["id"] if asset else None, duration=duration))
    return Board(
        shots=shots,
        narration=Narration(
            mode="uploaded" if audio else "silent", asset_id=audio["id"] if audio else None
        ),
    ).model_dump()


def validate_board(job, data):
    try:
        board = Board.model_validate(data).model_dump()
    except ValidationError as exc:
        raise ValueError("分镜参数无效：" + str(exc)) from exc
    lines = job["script"].splitlines()
    if len(board["shots"]) != len(lines):
        raise ValueError("分镜数必须与已保存脚本行数一致")
    assets = {a["id"]: a for a in job["assets"]}
    total = 0
    for shot in board["shots"]:
        asset = assets.get(shot["asset_id"])
        if not asset or asset["kind"] == "audio":
            raise ValueError("每镜必须选择属于本任务的画面素材")
        shot["duration"] = round(shot["duration"] * 30) / 30
        shot["source_in"] = round(shot["source_in"] * 30) / 30
        total += shot["duration"]
        if shot.get("motion_plan") and any(
            w["end"] > shot["duration"] + 0.001 for w in shot["motion_plan"]["windows"]
        ):
            raise ValueError("动作保护区间超出本镜时长")
        if asset["kind"] == "video":
            if (
                not shot.get("source_cuts")
                and shot["source_in"] + shot["duration"] > metadata(asset)["duration"] + 0.001
            ):
                raise ValueError("视频选段超出源素材时长，请缩短镜头或调整入点")
            if shot["motion"] != "static":
                raise ValueError("图片运镜仅支持图片；视频请使用原素材镜头")
        else:
            if shot["source_in"]:
                raise ValueError("图片不支持视频入点")
            if shot["source_framing"] != "original":
                raise ValueError("方形取景仅支持视频，请核对素材类型")
    for shot, line in zip(board["shots"], lines, strict=True):
        validate_typography(shot.get("typography"), shot["headline"], line)
    validate_delivery(job, board)
    if total > 120:
        raise ValueError("分镜总时长不得超过 120 秒")
    voice = board["narration"]
    if voice["mode"] == "uploaded":
        a = assets.get(voice["asset_id"])
        if not a or a["kind"] != "audio":
            raise ValueError("请选择本任务的配音素材")
        if metadata(a)["duration"] > total + 0.001:
            raise ValueError("配音超过分镜总时长，请延长镜头，避免截断口播")
    elif voice["asset_id"] is not None:
        raise ValueError("仅上传配音模式可指定配音素材")
    if voice["mode"] == "local" and not capabilities()["local_tts"]:
        raise ValueError("当前系统不支持本机中文合成，请上传配音")
    if board["music_id"]:
        a = assets.get(board["music_id"])
        if not a or a["kind"] != "audio" or a["id"] == voice["asset_id"]:
            raise ValueError("背景音乐须为另一条本任务音频素材")
    if board.get("creative"):
        board["creative"] = validate_creative(job, board["creative"])
        board["creative_required"] = True
        ids = [s["shot_id"] for s in board["shots"]]
        if any(not x for x in ids) or len(set(ids)) != len(ids):
            raise ValueError("每镜需要唯一且稳定的 shot_id")
        for shot, line in zip(board["shots"], lines, strict=True):
            if shot["headline"] and shot["headline"] not in line:
                raise ValueError("动态字卡必须摘自本镜已确认脚本，避免新增产品事实")
    return board


def rebase_board(existing, script, seconds, assets):
    """Preserve edit decisions after text changes; invalidate creative/alignment consent."""
    import copy
    import difflib
    import uuid

    old = json.loads(existing["storyboard"])
    newlines = script.splitlines()
    oldlines = existing["script"].splitlines()
    fresh = default_board({"script": script, "seconds": seconds, "assets": assets})
    if len(newlines) == len(oldlines):
        shots = copy.deepcopy(old["shots"])
    else:
        shots = fresh["shots"]
        for block in difflib.SequenceMatcher(
            a=oldlines, b=newlines, autojunk=False
        ).get_matching_blocks():
            for offset in range(block.size):
                shots[block.b + offset] = copy.deepcopy(old["shots"][block.a + offset])
    for line, shot in zip(newlines, shots, strict=True):
        shot["shot_id"] = shot.get("shot_id") or "shot-" + uuid.uuid4().hex[:12]
        if shot.get("headline") and shot["headline"] not in line:
            shot["headline"] = ""
        if shot.get("typography"):
            try:
                validate_typography(shot["typography"], shot.get("headline", ""), line)
            except ValueError:
                shot["typography"] = None
    old["shots"] = shots
    old["previous_creative"] = old.get("creative") or old.get("previous_creative")
    if old["previous_creative"]:
        old["previous_creative"]["alignment_id"] = None
    old["creative"] = None
    old["creative_required"] = True
    return old
