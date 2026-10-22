"""Product evidence endpoints; no caller-supplied filesystem paths or model credentials."""

from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from .creative import Brief
from .db import Conflict
from .generation import compose, compose_directed, model_config
from .media import digest, safe_path
from .products import Products, uid
from .source_process import isolated
from .sources import MAX_DOCUMENT


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Create(Input):
    title: str = Field(min_length=1, max_length=120)


class Version(Input):
    revision: int = Field(ge=0)


class Link(Version):
    url: str = Field(min_length=1, max_length=2048)


class Quote(Version):
    source_id: str
    unit_id: str
    text: str = Field(min_length=1, max_length=100)


class Confirm(Version):
    reviewer: str = Field(min_length=1, max_length=80)
    note: str = Field(min_length=1, max_length=1000)
    confirmed: Literal[True]


class Facts(Confirm):
    fact_ids: list[str] = Field(min_length=1, max_length=20)


class Generate(Version):
    mode: Literal["extractive", "model", "directed"] = "extractive"
    external_consent: bool = False
    brief: Brief | None = None


class Alternatives(Version):
    brief: Brief = Field(default_factory=Brief)


class AdoptAlternative(Alternatives):
    basis: str = Field(pattern=r"^[a-f0-9]{64}$")
    candidate_id: Literal["overview", "details", "scene"]


class Scene(Input):
    text: str = Field(min_length=1, max_length=100)
    fact_ids: list[str] = Field(max_length=20)


class Draft(Version):
    scenes: list[Scene] = Field(min_length=1, max_length=30)


class Approval(Confirm):
    draft_id: str
    seconds: float = Field(default=3, ge=1, le=15)


def router(root, store):
    routes = APIRouter(prefix="/api/products")
    products = Products(store)

    def current(pid, revision):
        p = products.get(pid)
        if p["revision"] != revision:
            raise Conflict("资料已更新，请重新载入当前版本")
        return p

    def verify_sources(p):
        for source in p["sources"]:
            path = safe_path(root, source["path"])
            if not path.is_file() or digest(path) != source["sha256"]:
                raise Conflict("原始资料缺失或已变化，请恢复资料或创建新的资料夹")

    @routes.get("")
    def listing():
        return products.list()

    @routes.post("", status_code=201)
    def create(data: Create):
        return products.create(data.title)

    @routes.get("/capabilities")
    def capabilities():
        return {
            "documents": ["txt", "md", "pdf", "docx"],
            "model": model_config(),
            "script_generation": {
                "modes": ["extractive", "directed", "model"],
                "directed": "本机有限叙事模板、确认事实原文、逐句镜头目的；新稿需人工确认",
            },
            "max_document_bytes": MAX_DOCUMENT,
            "scope": "public_static_https",
        }

    @routes.get("/{pid}")
    def get(pid: str):
        return products.get(pid)

    @routes.post("/{pid}/documents", status_code=201)
    def document(pid: str, revision: Annotated[int, Form()], file: Annotated[UploadFile, File()]):
        current(pid, revision)
        sid = uid()
        name = (file.filename or "upload").replace("\\", "/").split("/")[-1][:180]
        suffix = Path(name).suffix.lower()
        if suffix not in (".txt", ".md", ".pdf", ".docx"):
            raise ValueError("支持 TXT、MD、文字 PDF 和 DOCX")
        relative = f"products/{pid}/sources/{sid}{suffix}"
        path = safe_path(root, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = file.file.read(MAX_DOCUMENT + 1)
            if not data or len(data) > MAX_DOCUMENT:
                raise ValueError("文档为空或超过 10 MiB")
            path.write_bytes(data)
            parsed = isolated({"operation": "document", "path": str(path), "filename": name})
            return products.add_source(
                pid,
                revision,
                {
                    "id": sid,
                    "kind": "document",
                    "file_name": name,
                    "path": relative,
                    "sha256": digest(path),
                    "extracted": parsed,
                },
            )
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        finally:
            file.file.close()

    @routes.post("/{pid}/links", status_code=201)
    def link(pid: str, data: Link):
        current(pid, data.revision)
        sid = uid()
        relative = f"products/{pid}/sources/{sid}.html"
        path = safe_path(root, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            parsed = isolated({"operation": "url", "url": data.url, "path": str(path)})
            return products.add_source(
                pid,
                data.revision,
                {
                    "id": sid,
                    "kind": "url",
                    "file_name": "网页快照.html",
                    "path": relative,
                    "sha256": digest(path),
                    "original_url": data.url,
                    "final_url": parsed.pop("final_url"),
                    "extracted": parsed,
                },
            )
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    @routes.get("/{pid}/sources/{sid}")
    def source_file(pid: str, sid: str):
        source = next((s for s in products.get(pid)["sources"] if s["id"] == sid), None)
        if not source:
            raise KeyError(sid)
        path = safe_path(root, source["path"])
        if not path.is_file():
            raise HTTPException(404, "原始资料缺失")
        return FileResponse(
            path, filename=source["file_name"], media_type="application/octet-stream"
        )

    @routes.post("/{pid}/quotes")
    def quote(pid: str, data: Quote):
        return products.add_quote(pid, data.revision, data.source_id, data.unit_id, data.text)

    @routes.post("/{pid}/facts/confirm")
    def facts(pid: str, data: Facts):
        verify_sources(current(pid, data.revision))
        return products.confirm_facts(pid, data.revision, data.fact_ids, data.reviewer, data.note)

    @routes.post("/{pid}/scripts/generate", status_code=201)
    def generate(pid: str, data: Generate):
        p = current(pid, data.revision)
        verify_sources(p)
        facts = products.confirmed_facts(p)
        model = None
        if data.mode == "model":
            if not data.external_consent:
                raise ValueError("请先确认将已确认事实发送给配置的模型服务")
            response = isolated({"operation": "model", "facts": facts}, timeout=45)
            scenes, model = response["scenes"], response["model"]
        elif data.mode == "directed":
            scenes = compose_directed(facts, data.brief.model_dump() if data.brief else {})
        else:
            scenes = compose(facts)
        return products.save_draft(pid, data.revision, scenes, data.mode, model)

    @routes.post("/{pid}/scripts/alternatives")
    def script_alternatives(pid: str, data: Alternatives):
        from .script_alternatives import alternatives

        p = current(pid, data.revision)
        verify_sources(p)
        from .customer import Customers
        from .material_suitability import material_inputs

        with store.connect() as c:
            customer = c.execute(
                "SELECT 1 FROM customer_projects WHERE product_id=?", (pid,)
            ).fetchone()
        project = Customers(root, store).get(pid) if customer else None
        assets, constraints = material_inputs(project) if project else ([], {})
        bundle = alternatives(
            p,
            products.confirmed_facts(p),
            data.brief.model_dump(),
            assets=assets,
            constraints=constraints,
        )
        if project:
            from .creative import signature
            from .production_proposals import analysis_basis

            bundle["customer_revision"] = project["revision"]
            bundle["material_analysis"] = analysis_basis(project["media"])
            bundle["basis"] = signature(
                {
                    "proposal": bundle["basis"],
                    "customer_revision": project["revision"],
                    "settings": project["settings"],
                    "material_analysis": bundle["material_analysis"],
                }
            )
        return bundle

    @routes.post("/{pid}/scripts/alternatives/adopt", status_code=201)
    def adopt_alternative(pid: str, data: AdoptAlternative):
        bundle = script_alternatives(pid, data)
        if bundle["basis"] != data.basis:
            raise Conflict("备选稿依据已变化，请重新生成比较后采用")
        chosen = next(c for c in bundle["candidates"] if c["id"] == data.candidate_id)
        from .production_proposals import ProposalGuard

        guard = (
            ProposalGuard(pid, bundle["customer_revision"], bundle["material_analysis"])
            if "customer_revision" in bundle
            else None
        )
        return products.save_draft(
            pid, data.revision, chosen["payload"], "alternative-" + data.candidate_id, receipt=guard
        )

    @routes.post("/{pid}/scripts", status_code=201)
    def edit(pid: str, data: Draft):
        return products.save_draft(
            pid, data.revision, [s.model_dump() for s in data.scenes], "human_edit"
        )

    @routes.post("/{pid}/scripts/confirm", status_code=201)
    def approve(pid: str, data: Approval):
        verify_sources(products.get(pid))
        return products.approve(
            pid, data.revision, data.draft_id, data.reviewer, data.note, data.seconds
        )

    return routes
