"""Pinned Lemo reference retrieval, not arbitrary code execution or model generation."""

import json
from functools import lru_cache
from pathlib import Path

from .creative import signature
from .media import digest

LIBRARY = Path(__file__).resolve().parent.parent / "vendor/lemo-opuscar/2026-10-reference"
KEYWORDS = {
    "whiteboard": "讲解 科普 教学 课程 学生 原理 科学 白板",
    "blueprint": "机械 结构 工程 原理 建筑 设计 图纸 技术 严谨",
    "dataviz": "数据 报告 图表 对比 统计 复盘",
    "swiss-motion": "品牌 字体 排版 活动 宣传 设计 简洁",
    "crayon-book": "儿童 童话 睡前 绘本 温暖 可爱",
    "watercolor": "温暖 柔和 水彩 儿童 诗意 旅行",
    "ink-wash": "水墨 古风 国风 江湖 文化 中国",
    "paper-popup": "故事 儿童 童话 纸张 立体 绘本",
    "pixel-rpg": "游戏 像素 冒险 角色 故事 年轻",
    "dark-keynote": "发布 科技 软件 介绍 极简 深色",
    "glass-product": "商品 数码 产品 精致 材质 透明",
    "teardown": "拆解 结构 部件 商品 原理",
    "caption-news": "新闻 知识 资讯 字幕 新闻稿",
    "news-package": "新闻 播报 周报 行业 资讯",
    "kino-montage": "实拍 服装 运动 节奏 快切 工业",
    "telestrator": "动作 讲解 体育 衣服 实拍 分析",
    "archive-lighttable": "历史 资料 文档 证据 照片",
    "iso-infographic": "流程 步骤 科普 解释 示意",
}
DEFAULTS = ["swiss-motion", "whiteboard", "blueprint", "paper-popup", "dark-keynote", "pixel-rpg"]


@lru_cache(maxsize=1)
def catalog():
    source = json.loads((LIBRARY / "SOURCES.json").read_text())
    hashes = {r["path"]: r["sha256"] for r in source["files"]}
    rows = []
    for path in sorted((LIBRARY / "styles").glob("*/style.json")):
        if path.parent.name == "_template":
            continue
        guide = path.with_name("STYLE.md")
        for file in (path, guide):
            if digest(file) != hashes[file.relative_to(LIBRARY).as_posix()]:
                raise ValueError("风格参考文件校验失败，请恢复固定版本")
        meta = json.loads(path.read_text())
        rows.append(
            {
                "id": meta["slug"],
                "name": meta["cn"],
                "english": meta["en"],
                "category": meta["category_cn"],
                "uses": meta.get("uses", []),
                "prompt": guide.read_text(),
                "status": "reference",
                "source": {
                    "author": "LemoLab",
                    "license": "MIT (docs)",
                    "commit": source["commit"],
                    "url": f"{source['repository']}/blob/{source['commit']}/styles/{meta['slug']}/STYLE.md",
                },
            }
        )
    return rows


def recommend(idea, audience="", tone="", mode="code", preferred=None):
    query = " ".join((idea, audience, tone)).casefold()
    library = catalog()
    if preferred and preferred not in {r["id"] for r in library}:
        raise ValueError("请选择已登记的风格")

    def rank(row):
        tags = KEYWORDS.get(row["id"], "").split()
        matches = [tag for tag in tags if tag.casefold() in query]
        name_score = (
            5 if row["name"].casefold() in query or row["english"].casefold() in query else 0
        )
        base = 6 - DEFAULTS.index(row["id"]) if row["id"] in DEFAULTS else 0
        material_score = 0
        if mode == "footage":
            material_score = (
                120 if row["category"] in ("剪辑与纪实", "实证影像", "图形与排版") else -1000
            )
        return (
            (10000 if row["id"] == preferred else 0)
            + len(matches) * 20
            + name_score * 20
            + base
            + material_score
        )

    ordered = sorted(library, key=lambda r: (-rank(r), r["id"]))
    selected, categories = [], {}
    for row in ordered:
        if categories.get(row["category"], 0) >= 2:
            continue
        selected.append(row)
        categories[row["category"]] = categories.get(row["category"], 0) + 1
        if len(selected) == 6:
            break
    options = []
    for row in selected:
        matches = [t for t in KEYWORDS.get(row["id"], "").split() if t.casefold() in query]
        brief = (
            f"主题：{idea}\n受众：{audience or '待确认'}\n气质：{tone or '待选择'}\n"
            f"风格：{row['name']}（LemoLab参考，未宣称完整适配）\n"
            + (
                "使用现有实拍作为事实依据，不重绘商品或人物，不混款混色。\n"
                if mode == "footage"
                else "无素材时用代码图形、文字、图示组织讲解；示意画面不得伪装成真实人物、商品实拍或实验结果。\n"
            )
            + "先写可审阅文稿和分镜，再渲染。逐镜说明表达目的、画面依据、关键词、声音锚点及回退。\n"
            "角色/内容设定在本片锁定；换风格不改变已确认事实。参考原片中的故事、数字、人物和配音不继承为本片事实或素材。\n"
            "事实、文稿、风格、听核和成片审核仍待人工确认，不自动投放。\n\n--- 上游风格资料（只读参考）---\n"
            + row["prompt"]
        )
        options.append(
            {
                **{k: v for k, v in row.items() if k != "prompt"},
                "reason": "匹配：" + "、".join(matches)
                if matches
                else "补充不同的视觉讲法，仍须人工判断是否适合此内容",
                "adapted_prompt": brief,
                "preview_note": "当前是有来源的创作方案；上游参考不等于当前渲染器已执行的成片。",
            }
        )
    return {
        "version": "film-reference-v1",
        "basis": signature(
            {
                "idea": idea,
                "audience": audience,
                "tone": tone,
                "mode": mode,
                "preferred": preferred,
                "sources": [o["source"] for o in options],
            }
        ),
        "idea": idea,
        "audience": audience,
        "tone": tone,
        "mode": mode,
        "options": options,
        "approvals": [],
        "library_count": len(library),
        "method": "固定来源＋本机关键词检索与类别去重；不是自由模型写稿，未执行上游代码。",
    }
