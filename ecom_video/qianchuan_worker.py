"""One-shot uploads/creates; bounded read polling; unknown outcomes never retry."""

import shutil
import time
from contextlib import suppress

from .db import Conflict
from .media import digest, safe_path
from .platforms.secret_store import task_ownership
from .qianchuan_tasks import checksum, create_payload


def execute(service, task):
    if not task:
        return
    with task_ownership(service.root, task["id"]) as owned:
        if owned:
            _execute_owned(service, task)


def _execute_owned(service, task):
    try:
        config, grant = service._context(task, True)
        auth = service.auth
        token = auth.token(task["account_id"])
        account = task["source_snapshot"]["account"]
        provider = auth.provider
        if not provider.authorized(token, account["advertiser_id"]):
            raise Conflict("平台当前不再授权该广告主，请重新授权")
        if task["stage"] == "upload":
            if not task["upload_approval"]:
                raise Conflict("缺少人工上传确认")
            artifact = next(a for a in task["source_snapshot"]["artifacts"] if a["kind"] == "video")
            copy = safe_path(service.root, f"qianchuan/{task['id']}/{task['lease_token']}.mp4")
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(safe_path(service.root, artifact["path"]), copy)
            if digest(copy) != artifact["sha256"]:
                raise Conflict("成片复制校验失败，未上传")
            service.mark_dispatch(task)
            material = provider.upload(
                token, account["advertiser_id"], copy, task["parameters"]["is_aigc"]
            )
            material["video_sha256"] = artifact["sha256"]
            service.finish(
                task,
                "material_pending",
                "上传已收到回执；等待素材库可查询，不代表平台审核通过",
                material=material,
                next_check_at=time.time() + 30,
                dispatch_started=0,
            )
        elif task["stage"] == "check":
            material = task["material"]
            verified = provider.material(
                token,
                account["advertiser_id"],
                material["video_id"],
                material["md5"],
                material["material_id"],
            )
            if verified is None:
                service.finish(
                    task,
                    "material_pending",
                    "平台素材库尚未查到该素材；达到 20 次后可手动继续查询",
                    next_check_at=time.time() + 30 if task["check_attempts"] < 20 else None,
                )
                return
            material = {
                **material,
                "verified_at": time.time(),
                "verification_request_id": verified["request_id"],
            }
            task["material"] = material
            payload = {
                "request": create_payload(task),
                "context": {
                    "account_id": task["account_id"],
                    "grant_id": grant["id"],
                    "config_revision": config["revision"],
                    "video_sha256": material["video_sha256"],
                    "material_id": material["material_id"],
                    "source_hash": checksum(task["source_snapshot"]),
                    "prepared_at": time.time(),
                },
            }
            service.finish(
                task,
                "awaiting_approval",
                "素材身份已核对；请确认精确广告参数，可能立即产生费用",
                material=material,
                payload=payload,
                snapshot_hash=checksum(payload),
                prepared_until=time.time() + 900,
                grant_id=grant["id"],
                config_revision=config["revision"],
            )
        elif task["stage"] == "create":
            approval = task["approval"]
            payload = task["payload"]
            if (
                not approval
                or not payload
                or approval["snapshot_hash"] != task["snapshot_hash"]
                or checksum(payload) != task["snapshot_hash"]
                or payload["request"] != create_payload(task)
                or task["prepared_until"] <= time.time()
                or approval["at"] + 900 <= time.time()
            ):
                raise Conflict("广告确认已变化、过期或缺失，未提交")
            context = payload["context"]
            if (
                context["grant_id"] != grant["id"]
                or context["config_revision"] != config["revision"]
                or context["source_hash"] != checksum(task["source_snapshot"])
            ):
                raise Conflict("提交上下文发生变化，未提交")
            material = task["material"]
            if (
                provider.material(
                    token,
                    account["advertiser_id"],
                    material["video_id"],
                    material["md5"],
                    material["material_id"],
                )
                is None
            ):
                raise Conflict("提交前素材已不可查询，请重新核验")
            service.mark_dispatch(task)
            result = provider.create(token, payload["request"])
            service.finish(
                task, "submitted", "平台返回广告计划 ID；不代表已通过审核或开始投放", result=result
            )
        else:
            raise Conflict("任务执行阶段无效")
    except Exception as error:
        with suppress(Conflict):  # Recovery may already have fenced this process.
            service.fail(task, error)
