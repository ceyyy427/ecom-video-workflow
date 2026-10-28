"""Read only the pinned text snapshot; never execute or download toolkit methods."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from pydantic import ConfigDict, Field, ValidationError, model_validator

from ..agent_contracts import Strict
from ..maintenance import local_path
from .contracts import Sha256, SourceVersion

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOCK = ROOT / "docs/third-party/domestic-toolkit.lock.json"
MAX_LOCK_BYTES = 512 * 1024
MAX_FILE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024
UPSTREAM = "heqiangdiao-wq/AI-Cross-Border-Ecommerce-Agent-Toolkit"
FORK = "ceyyy427/AI-Cross-Border-Ecommerce-Agent-Toolkit"


class ResourceError(ValueError):
    pass


def no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ResourceError("资源清单有重复 JSON 字段")
        result[key] = value
    return result


class ResourceSource(SourceVersion):
    model_config = ConfigDict(frozen=True)
    path: str = Field(min_length=1, max_length=240)


class ResourceEntry(Strict):
    model_config = ConfigDict(frozen=True)
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,99}$")
    path: str = Field(min_length=1, max_length=240)
    sha256: Sha256
    size_bytes: int = Field(ge=1, le=MAX_FILE_BYTES)
    source: ResourceSource
    kind: str
    status: str

    @model_validator(mode="after")
    def coherent(self):
        if self.kind not in {
            "license",
            "readme",
            "prompt",
            "template",
            "reference",
            "script",
            "manifest",
        }:
            raise ValueError("仅允许已登记的文本资源类型")
        if self.status != "reference":
            raise ValueError("D0 资料只可登记为参考，不能代替适配或实测")
        allowed = {".md", ".txt", ".yaml", ".yml", ".json", ".py"}
        if self.path != "LICENSE" and PurePosixPath(self.path).suffix not in allowed:
            raise ValueError("只接受文本参考，不能登记可执行安装文件或媒体")
        return self


class License(Strict):
    spdx: str
    path: str
    sha256: Sha256


class ResourceLock(Strict):
    schema_version: int
    bundle_id: str
    resource_root: str
    upstream: SourceVersion
    fork: SourceVersion
    license: License
    files: list[ResourceEntry] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def coherent(self):
        if (
            self.schema_version != 1
            or self.bundle_id != "domestic-toolkit-d0"
            or self.resource_root != "resources/domestic-toolkit"
        ):
            raise ValueError("不支持的资源锁版本或目录")
        if self.upstream.repository != UPSTREAM or self.fork.repository != FORK:
            raise ValueError("来源仓库与当前可信清单不一致")
        if self.license.spdx != "MIT" or self.license.path != "LICENSE":
            raise ValueError("资源包须保留上游 MIT 原文")
        if len({r.id for r in self.files}) != len(self.files) or len(
            {r.path for r in self.files}
        ) != len(self.files):
            raise ValueError("资源 ID 或路径重复")
        for r in self.files:
            expected = (
                self.upstream
                if r.source.repository == UPSTREAM
                else self.fork
                if r.source.repository == FORK
                else None
            )
            if expected is None or r.source.commit != expected.commit:
                raise ValueError("资源来源提交与固定版本不符")
            source_path = (
                "LICENSE"
                if r.path == "LICENSE"
                else (
                    r.path.removeprefix("upstream/")
                    if r.source.repository == UPSTREAM
                    else "Domestic/" + r.path.removeprefix("domestic/")
                )
            )
            if source_path != r.source.path:
                raise ValueError("资源路径与来源文件不一致")
        licenses = [r for r in self.files if r.path == "LICENSE" and r.kind == "license"]
        if len(licenses) != 1 or licenses[0].sha256 != self.license.sha256:
            raise ValueError("MIT 声明未登记或指纹不一致")
        if sum(r.size_bytes for r in self.files) > MAX_TOTAL_BYTES:
            raise ValueError("资源包超过总大小限制")
        return self


@dataclass(frozen=True)
class ResourceBundle:
    upstream_commit: str
    fork_repository: str
    fork_commit: str
    license_id: str
    entries: tuple
    _texts: tuple

    def read(self, resource_id):
        for key, text in self._texts:
            if key == resource_id:
                return text
        raise ResourceError("没有该资源 ID")


def load_resources(lock_path=DEFAULT_LOCK, *, project_root=None):
    root = Path(project_root).resolve() if project_root is not None else ROOT
    try:
        lock_path = Path(lock_path)
        if (
            lock_path.is_symlink()
            or not lock_path.is_file()
            or lock_path.stat().st_size > MAX_LOCK_BYTES
        ):
            raise ResourceError("资源清单不是有效的小型普通文件")
        data = json.loads(lock_path.read_bytes(), object_pairs_hook=no_duplicate_keys)
        lock = ResourceLock.model_validate(data)
        texts = []
        for item in lock.files:
            path = local_path(root, f"{lock.resource_root}/{item.path}")
            if not path.is_file() or path.stat().st_size != item.size_bytes:
                raise ResourceError("参考文件缺失或大小不一致")
            with path.open("rb") as stream:
                raw = stream.read(MAX_FILE_BYTES + 1)
            if len(raw) != item.size_bytes or hashlib.sha256(raw).hexdigest() != item.sha256:
                raise ResourceError("参考文件 SHA256 校验失败")
            texts.append((item.id, raw.decode("utf-8")))
        return ResourceBundle(
            lock.upstream.commit,
            lock.fork.repository,
            lock.fork.commit,
            lock.license.spdx,
            tuple(lock.files),
            tuple(texts),
        )
    except ResourceError:
        raise
    except (OSError, UnicodeError, ValueError, ValidationError, TypeError, RecursionError) as exc:
        raise ResourceError("无法读取已固定资源；请核对来源、许可、路径和哈希") from exc
