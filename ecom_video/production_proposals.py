"""Joint local proposals reuse the existing editorial and material safety policies."""

from .creative import recommend, signature
from .db import Conflict
from .material_suitability import fit_summary
from .readiness import check_materials

VERSION = "customer-production-v1"


def analysis_basis(media):
    return {
        a["id"]: signature(
            {k: a["analysis"].get(k) for k in ("id", "status", "source_sha256", "result")}
        )
        if a.get("analysis")
        else None
        for a in media
        if a["kind"] != "audio"
    }


class ProposalGuard:
    """Close the preview/adoption race in the same draft-write transaction."""

    def __init__(self, pid, revision, analyses):
        self.pid, self.revision, self.analyses = pid, revision, analyses

    def guard(self, c):
        row = c.execute(
            "SELECT revision FROM customer_projects WHERE product_id=?", (self.pid,)
        ).fetchone()
        if not row or row[0] != self.revision:
            raise Conflict("商品素材或制作要求已变化，请重新比较备选方案")
        from .media_analysis import attach

        media = [
            dict(a)
            for a in c.execute("SELECT id,kind FROM customer_media WHERE product_id=?", (self.pid,))
        ]
        if analysis_basis(attach(c, media)) != self.analyses:
            raise Conflict("素材识别依据已变化，请重新比较备选方案")

    def __call__(self, c, draft_id):
        pass


def material_inventory(assets):
    visuals = [a for a in assets if a["kind"] != "audio"]
    images = sum(a["kind"] == "image" for a in visuals)
    videos = len(visuals) - images
    rows, unknown = [], 0
    for asset in visuals:
        meta = asset.get("metadata", {})
        analysis = meta.get("content_analysis") or {}
        observed = bool(
            analysis.get("source_sha256") == asset["sha256"]
            and not asset.get("analysis_stale")
            and analysis.get("recognition", "complete") == "complete"
        )
        unknown += not observed
        rows.append(
            {
                "asset_id": asset["id"],
                "name": asset["name"],
                "kind": asset["kind"],
                "width": meta.get("width"),
                "height": meta.get("height"),
                "duration": meta.get("duration"),
                "codec": meta.get("codec"),
                "observations": "available_not_verified" if observed else "unknown",
                "intake": meta.get("intake"),
            }
        )
    warnings = ["同款、不同配色与模特/音乐等使用权限仍须人工核对；素材用途标签不是视觉或授权证明"]
    if not videos:
        warnings.append("当前无实拍视频；图片运镜不能替代穿着、倒水或开盖等实际动作")
    if unknown:
        warnings.append(
            f"{unknown}份画面未取得当前有效识别，内容匹配与动作完整性保留未知，可识别或逐镜人工安排"
        )
    return {
        "version": VERSION,
        "images": images,
        "videos": videos,
        "unknown_visuals": unknown,
        "same_product": "pending_human",
        "rights": "pending_human",
        "human_review_required": True,
        "scope": "技术可读性与素材清单；不是SKU、主体可见度或完整动作认证",
        "warnings": warnings,
        "assets": rows,
    }


def production_readiness(lines, assets, constraints, style, brief):
    report = check_materials(lines, assets, constraints=constraints)
    fit = fit_summary(report, style, assets=assets, constraints=constraints, format=brief["format"])
    return {"inventory": material_inventory(assets), "fit": fit, "lines": report["lines"]}


def enrich_candidates(candidates, product, brief, assets, constraints, facts):
    # Each family offers a different visual grammar; no new engine or model policy.
    family = {"overview": "premium", "details": "demo", "scene": "lifestyle"}
    for candidate in candidates:
        rows = candidate["payload"]
        job = {
            "title": product["title"],
            "script": "\n".join(s["text"] for s in rows),
            "assets": assets,
            "provenance": {"facts": facts, "scenes": rows},
        }
        rec = recommend(job, brief)
        direction = next(o for o in rec["options"] if o["family"] == family[candidate["id"]])
        readiness = production_readiness(
            job["script"].splitlines(), assets, constraints, direction["id"], brief
        )
        candidate.update(
            direction=direction,
            inventory=readiness["inventory"],
            material_fit=readiness["fit"],
            estimated_seconds=round(sum(r["duration"] for r in readiness["lines"]), 2),
            timing_basis="文稿估算，非20–30秒保证；配音试听与实测对齐后重检",
        )
        for plan, row in zip(candidate["shot_strategies"], readiness["lines"], strict=True):
            plan["material"] = row
        candidate["production_notes"] = {
            "audience": brief["audience"],
            "tone": brief["tone"],
            "structure": direction["production"]["structure"],
            "rhythm": direction["production"]["rhythm"],
            "adoption": "采用只创建待确认文稿；文稿确认后重新选定推荐风格和配音，并逐句听核",
        }
