"""Read-only, explicitly unapproved demonstration films; no task or review mutation."""

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

LIBRARY = Path(__file__).resolve().parents[1] / "examples/client-demo"
KINDS = {
    "video": "output.mp4",
    "poster": "poster.jpg",
    "shotbook": "shotbook.json",
    "subtitles": "subtitles.srt",
    "narration": "narration.wav",
}
STYLES = ("cinema", "social", "lab")
CONTEXTUAL_LIBRARY = LIBRARY.parent / "contextual-demo"
CONTEXTUAL_STYLES = ("quiet", "editorial", "evidence")
CONTEXTUAL_KINDS = {
    **KINDS,
    "parent": "parent.mp4",
    "old": "old.wav",
    "new": "new.wav",
    "recommendations": "recommendations.json",
    "selection": "manual-selection.json",
}
CATEGORY_LIBRARY = LIBRARY.parent / "category-demo"
CATEGORY_IDS = ("headphones", "serum")
MOTION_LIBRARY = LIBRARY.parent / "motion-demo"
NARRATIVE_LIBRARY = LIBRARY.parent / "narrative-demo"
PRODUCTION_LIBRARY = LIBRARY.parent / "production-demo"
QUALITY_LIBRARY = LIBRARY.parent / "quality-demo"
REFINEMENT_LIBRARY = LIBRARY.parent / "refinement-demo"
FRAMING_LIBRARY = LIBRARY.parent / "framing-demo"
PROMPT_LIBRARY = LIBRARY.parent / "prompt-demo"
PROMPT_CATEGORY_LIBRARY = LIBRARY.parent / "prompt-category-demo"
FULL_LIBRARY_MOTION = LIBRARY.parent / "library-motion-demo"
PRODUCT_CARD_LIBRARY = LIBRARY.parent / "product-card-demo"
SEMANTIC_LIBRARY = LIBRARY.parent / "semantic-demo"
MATERIAL_LIBRARY = LIBRARY.parent / "material-demo"
READINESS_LIBRARY = LIBRARY.parent / "readiness-demo"
MOTION_KINDS = {
    "video": "output.mp4",
    "parent": "parent.mp4",
    "poster": "poster.jpg",
    "shotbook": "shotbook.json",
    "subtitles": "subtitles.srt",
    "retake": "retake.mp4",
}


def artifact(style, kind, *, library=None, styles=STYLES, kinds=KINDS):
    library = LIBRARY if library is None else library
    if style not in styles or kind not in kinds:
        raise HTTPException(404, "示例文件不存在")
    path = library / style / kinds[kind]
    if (
        path.is_symlink()
        or path.parent.is_symlink()
        or not path.is_file()
        or not path.resolve().is_relative_to(library.resolve())
    ):
        raise HTTPException(404, "示例文件不存在")
    return path


def entries(*, library=None, styles=STYLES, kinds=KINDS, minimum=20):
    library = LIBRARY if library is None else library
    try:
        rows = json.loads((library / "library.json").read_text())["samples"]
    except (OSError, ValueError, KeyError, TypeError):
        return []
    result = []
    for row in rows:
        try:
            artifact(row["style"], "video", library=library, styles=styles, kinds=kinds)
            if not minimum <= row["duration"] <= (30 if minimum == 20 else 120):
                continue
            result.append(
                {k: row.get(k) for k in ("style", "title", "description", "duration", "hook")}
                | {
                    "status": "needs_review",
                    "review_required": ["facts", "script", "style", "listening", "film"],
                }
            )
        except (HTTPException, KeyError, TypeError):
            continue
    return result


def router():
    api = APIRouter(prefix="/api/samples/client")

    @api.get("")
    def listing():
        return entries()

    @api.get("/{style}/{kind}")
    def file(style: str, kind: str, download: bool = False):
        if style not in {row["style"] for row in entries()}:
            raise HTTPException(404, "示例未就绪")
        path = artifact(style, kind)
        return FileResponse(path, filename=f"demo-{style}-{path.name}" if download else None)

    return api


def comparison_router(prefix, options, *, minimum=1, require_styles=None, required_kinds=()):
    api = APIRouter(prefix=prefix)

    @api.get("")
    def listing():
        rows = entries(**options(), minimum=minimum)
        try:
            for row in rows:
                for kind in required_kinds:
                    artifact(row["style"], kind, **options())
        except HTTPException:
            return []
        if require_styles is not None and {r["style"] for r in rows} != set(require_styles):
            return []
        return rows

    @api.get("/{style}/{kind}")
    def file(style: str, kind: str, download: bool = False):
        if style not in {row["style"] for row in listing()}:
            raise HTTPException(404, "示例未就绪")
        path = artifact(style, kind, **options())
        return FileResponse(path, filename=f"contextual-{style}-{path.name}" if download else None)

    return api


def contextual_router():
    return comparison_router(
        "/api/samples/contextual",
        lambda: {
            "library": CONTEXTUAL_LIBRARY,
            "styles": CONTEXTUAL_STYLES,
            "kinds": CONTEXTUAL_KINDS,
        },
    )


def category_router():
    return comparison_router(
        "/api/samples/categories",
        lambda: {"library": CATEGORY_LIBRARY, "styles": CATEGORY_IDS, "kinds": CONTEXTUAL_KINDS},
    )


def motion_router():
    return comparison_router(
        "/api/samples/motion",
        lambda: {"library": MOTION_LIBRARY, "styles": CATEGORY_IDS, "kinds": MOTION_KINDS},
    )


def narrative_router():
    return comparison_router(
        "/api/samples/narrative",
        lambda: {
            "library": NARRATIVE_LIBRARY,
            "styles": STYLES,
            "kinds": {**KINDS, "parent": "parent.mp4", "retake": "retake.mp4"},
        },
        minimum=20,
        require_styles=STYLES,
    )


def production_router():
    return comparison_router(
        "/api/samples/production",
        lambda: {
            "library": PRODUCTION_LIBRARY,
            "styles": ("headphones",),
            "kinds": {**CONTEXTUAL_KINDS, "retake": "retake.mp4"},
        },
    )


def readiness_router():
    return comparison_router(
        "/api/samples/readiness",
        lambda: {
            "library": READINESS_LIBRARY,
            "styles": ("headphones",),
            "kinds": {
                **KINDS,
                "report": "audit.html",
                "audit": "audit.json",
                "script": "script.json",
                "preflight": "preflight.json",
                "selection": "manual-selection.json",
            },
        },
    )


def quality_router():
    return comparison_router(
        "/api/samples/quality",
        lambda: {
            "library": QUALITY_LIBRARY,
            "styles": STYLES,
            "kinds": {**KINDS, "parent": "parent.mp4", "retake": "retake.mp4"},
        },
        minimum=20,
        require_styles=STYLES,
    )


def prompt_router():
    kinds = {
        **KINDS,
        "parent": "parent.mp4",
        "retake": "retake.mp4",
        "recommendations": "recommendations.json",
        "prompts": "prompts.json",
    }
    styles = ("social", "kinetic", "evidence")
    return comparison_router(
        "/api/samples/prompts",
        lambda: {"library": PROMPT_LIBRARY, "styles": styles, "kinds": kinds},
        minimum=20,
        require_styles=styles,
        required_kinds=tuple(kinds),
    )


def prompt_category_router():
    kinds = {
        **KINDS,
        "parent": "parent.mp4",
        "retake": "retake.mp4",
        "recommendations": "recommendations.json",
        "prompts": "prompts.json",
    }
    styles = ("editorial", "quiet", "evidence")
    return comparison_router(
        "/api/samples/prompt-categories",
        lambda: {"library": PROMPT_CATEGORY_LIBRARY, "styles": styles, "kinds": kinds},
        minimum=1,
        require_styles=styles,
        required_kinds=tuple(kinds),
    )


def full_library_motion_router():
    kinds = {
        **KINDS,
        "parent": "parent.mp4",
        "retake": "retake.mp4",
        "recommendations": "recommendations.json",
        "prompts": "prompts.json",
    }
    styles = ("editorial", "evidence", "collage")
    return comparison_router(
        "/api/samples/library-motion",
        lambda: {"library": FULL_LIBRARY_MOTION, "styles": styles, "kinds": kinds},
        minimum=1,
        require_styles=styles,
        required_kinds=tuple(kinds),
    )


def framing_router():
    kinds = {**KINDS, "parent": "parent.mp4", "retake": "retake.mp4", "framing": "framing.json"}
    return comparison_router(
        "/api/samples/framing",
        lambda: {"library": FRAMING_LIBRARY, "styles": ("headphones",), "kinds": kinds},
        require_styles=("headphones",),
        required_kinds=tuple(kinds),
    )


def refinement_router():
    return comparison_router(
        "/api/samples/refinement",
        lambda: {
            "library": REFINEMENT_LIBRARY,
            "styles": CATEGORY_IDS,
            "kinds": {
                **KINDS,
                "parent": "parent.mp4",
                "retake": "retake.mp4",
                "recommendations": "recommendations.json",
                "treatment": "treatment.json",
                "selection": "manual-selection.json",
            },
        },
        require_styles=CATEGORY_IDS,
        required_kinds=(
            "video",
            "parent",
            "retake",
            "poster",
            "narration",
            "subtitles",
            "shotbook",
            "recommendations",
            "treatment",
            "selection",
        ),
    )


def product_cards_router():
    kinds = {
        **KINDS,
        "retake": "retake.mp4",
        "recommendations": "recommendations.json",
        "prompts": "prompts.json",
    }
    styles = ("evidence", "collage", "cinema")
    return comparison_router(
        "/api/samples/product-cards",
        lambda: {"library": PRODUCT_CARD_LIBRARY, "styles": styles, "kinds": kinds},
        minimum=1,
        require_styles=styles,
        required_kinds=tuple(kinds),
    )


def semantic_mix_router():
    kinds = {
        **KINDS,
        "retake": "retake.mp4",
        "detail-retake": "detail-retake.mp4",
        "recommendations": "recommendations.json",
        "prompts": "prompts.json",
        "alternatives": "alternatives.json",
    }
    styles = ("evidence", "collage", "editorial")
    return comparison_router(
        "/api/samples/semantic-mix",
        lambda: {"library": SEMANTIC_LIBRARY, "styles": styles, "kinds": kinds},
        minimum=20,
        require_styles=styles,
        required_kinds=tuple(kinds),
    )


def material_router():
    kinds = {
        **KINDS,
        "retake": "retake.mp4",
        "recognition": "recognition.json",
        "preflight": "preflight.json",
        "selection": "selection.json",
        "recommendations": "recommendations.json",
        "license": "license.json",
        "acceptance": "acceptance.json",
    }
    return comparison_router(
        "/api/samples/material-checks",
        lambda: {"library": MATERIAL_LIBRARY, "styles": ("cup",), "kinds": kinds},
        minimum=1,
        require_styles=("cup",),
        required_kinds=tuple(kinds),
    )
