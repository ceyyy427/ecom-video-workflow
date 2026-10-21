"""Pinned, project-authored prompts translated into finite local render recipes.

No live fetch, LLM call, code execution or unlicensed demo assets at production time.
Card IDs are immutable versions; saved shots never run keyword matching again.
"""

import copy
import hashlib
import json
import re
from collections import Counter
from typing import Literal

VERSION = "product-prompts-v1"
PromptCardId = Literal[
    "detail-bracket-soft-v1",
    "detail-bracket-bold-v1",
    "fact-row-soft-v1",
    "fact-row-bold-v1",
    "hero-soft-v1",
    "hero-bold-v1",
    "relay-soft-v1",
    "relay-bold-v1",
    "brand-soft-v1",
    "brand-bold-v1",
    "tech-punch-v1",
    "sport-punch-v1",
    "daily-punch-v1",
    "precision-dual-v1",
    "texture-dual-v1",
    "usage-dual-v1",
    "quiet-portal-v1",
    "warm-portal-v1",
    "color-portal-v1",
    "beauty-punch-v1",
    "beauty-portal-v1",
    "bottle-dual-v1",
    "food-punch-v1",
    "food-dual-v1",
    "food-portal-v1",
    "garment-punch-v1",
    "garment-dual-v1",
    "garment-portal-v1",
    "home-punch-v1",
    "home-dual-v1",
    "home-portal-v1",
    "tool-punch-v1",
    "tool-dual-v1",
    "tool-portal-v1",
    "type-mask-clean-v1",
    "type-mask-bold-v1",
    "comic-panels-soft-v1",
    "comic-panels-bold-v1",
]
BASE_MEDIA_RECIPES = {"media-punch-in", "detail-dual-window", "product-shape-reveal"}
MEDIA_RECIPES = BASE_MEDIA_RECIPES | {
    "product-detail-bracket",
    "product-fact-row",
    "product-type-mask",
    "same-frame-panels",
    "product-hero-stage",
    "product-explain-relay",
    "product-brand-snap",
}
SHOTCRAFT = {
    "repository": "Vincentwei1021/video-shotcraft",
    "commit": "43bd349a136651865ecfa6ea1cf012f6e957d304",
    "license": "Apache-2.0",
    "url": "https://vincentwei1021.github.io/video-shotcraft/source/crash-zoom-punch.md",
    "local_reference": "vendor/video-shotcraft/2026-10-motion/references/shots/camera/crash-zoom-punch.md",
}
PHOTO = {
    "repository": "alchaincyf/huashu-motion",
    "commit": "3e927801e78b587878fb7dbb65d616326df00c21",
    "license": "MIT",
    "url": "https://github.com/alchaincyf/huashu-motion/blob/3e927801e78b587878fb7dbb65d616326df00c21/skills/huashu-motion/references/library/languages/photo-led.md",
    "local_reference": "vendor/huashu-motion/skills/huashu-motion/references/library/languages/photo-led.md",
}
# These are original adaptations, not promises that an upstream UI demo fits a SKU.
_ROWS = [
    (
        "tech-punch-v1",
        "科技定点急推",
        "media-punch-in",
        "数码 科技 通勤 耳机 专业 利落",
        1.18,
        10,
        "rounded",
    ),
    (
        "sport-punch-v1",
        "活力商品重拍",
        "media-punch-in",
        "年轻 学生 运动 活泼 节奏 潮流",
        1.23,
        7,
        "diagonal",
    ),
    (
        "daily-punch-v1",
        "日常轻推点题",
        "media-punch-in",
        "生活 亲切 日常 家居 食品 自然",
        1.12,
        16,
        "circle",
    ),
    (
        "precision-dual-v1",
        "理性结构双窗",
        "detail-dual-window",
        "测评 理性 参数 数码 工具 严谨 接口",
        1.65,
        14,
        "rounded",
    ),
    (
        "texture-dual-v1",
        "材质纹理双窗",
        "detail-dual-window",
        "美妆 材质 纹理 精致 工艺 瓶身 珠宝",
        1.45,
        20,
        "rounded",
    ),
    (
        "usage-dual-v1",
        "日常细节双窗",
        "detail-dual-window",
        "使用 通勤 办公 生活 咖啡 说明",
        1.5,
        16,
        "circle",
    ),
    (
        "quiet-portal-v1",
        "克制轮廓展开",
        "product-shape-reveal",
        "高级 克制 安静 精致 沉静 工艺",
        1.0,
        26,
        "rounded",
    ),
    (
        "warm-portal-v1",
        "温暖圆窗展开",
        "product-shape-reveal",
        "温暖 自然 温柔 家居 咖啡 生活",
        1.0,
        30,
        "circle",
    ),
    (
        "color-portal-v1",
        "活泼斜面展开",
        "product-shape-reveal",
        "活泼 年轻 撞色 潮流 玩具 运动",
        1.0,
        18,
        "diagonal",
    ),
]
INSTRUCTIONS = {
    "media-punch-in": "先让观众看清商品整体，在对应口播摘句到来时向已核对焦点短促推近，落定留看，再回到整体。只处理真实画面，不震屏、不闪白、不改变源视频速度；动作保护区间内关闭。",
    "detail-dual-window": "上窗持续显示同一时刻的商品整体，下窗同步展示同一画面的焦点放大。先落整体，再展开细节窗；标明整体与细节视图。不是前后效果对比，不生成内部结构或测量结论，动作段保持完整单窗。",
    "product-shape-reveal": "从商品焦点附近的可见窗口展开完整实拍，底层保留低亮度同帧画面，避免空白开场。展开后保持清楚留看，字幕独立稳定；不抠造轮廓、不生成新的商品角度。",
}
CARDS = {
    rid: {
        "id": rid,
        "name": name,
        "recipe": recipe,
        "keywords": words.split(),
        "prompt": INSTRUCTIONS[recipe],
        "source": dict(SHOTCRAFT if recipe == "media-punch-in" else PHOTO),
        "adaptation": "本项目原创竖屏适配；引用镜头方法，不执行上游代码或生成商品事实",
        "presentation": {"zoom": zoom, "travel_frames": frames, "shape": shape},
        "requirements": [
            "有使用权的同款商品画面",
            "短边至少720像素",
            "人工核对焦点、裁切和动作保护区间",
        ],
    }
    for rid, name, recipe, words, zoom, frames, shape in _ROWS
}


# New immutable cards extend the library; VERSION stays v1 so frozen original
# card digests and saved shot contracts remain byte-for-byte stable.
CATALOG_REVISION = "product-prompts-2026-10-19-expanded"
_CATEGORY_ROWS = [
    (
        "beauty",
        "包装焦点",
        "美妆 护肤 包装 滴管 瓶身 瓶盖 瓶口",
        {
            "punch": (
                "瓶身点题轻推",
                1.16,
                14,
                "rounded",
                "让观众先辨认瓶身和盖体配色，再靠近外观焦点",
                "在‘瓶身/瓶盖’对应字锚点后推进，先完整认物，再留看色泽。不要用放大暗示护肤效果。",
            ),
            "dual": (
                "瓶口整体与细节",
                1.55,
                18,
                "rounded",
                "保留整瓶参照，让瓶口、盖体位置关系易懂",
                "两个窗口只放同一时刻，局部窗口聚焦已核对瓶口。旋开、提起滴管时回到完整单窗，不能把仍闭合的盖体说成已打开。",
            ),
            "portal": (
                "包装轮廓柔展",
                1.0,
                26,
                "rounded",
                "先给包装一个可辨轮廓，再展开手持实拍",
                "窗口只在外观句展开，落定后让出阅读时间。开盖与提起滴管保持原速，字幕不跟着窗口缩放。",
            ),
        },
    ),
    (
        "food",
        "食品外观",
        "食品 零食 饼干 曲奇 面包 烘焙 下午茶",
        {
            "punch": (
                "食品表面点题",
                1.19,
                10,
                "circle",
                "让真实表面纹理成为开场观看理由",
                "从完整食品轻快推进到实际纹理，留看后回位。咬开、掰开等动作不叠加急推；不凭外观宣称口感、配方或热量。",
            ),
            "dual": (
                "整份与纹理同步",
                1.6,
                16,
                "rounded",
                "同时交代整份外观和真实表面细节",
                "整体留上窗，下窗看同帧纹理；不是大小/成分检测。字幕讲到表面后才展开，不用图形补出夹心。",
            ),
            "portal": (
                "餐桌圆窗开场",
                1.0,
                22,
                "circle",
                "从一处真实食物细节展开餐桌关系",
                "圆窗展开至清楚整幅实拍后停止，手部入镜时不遮住关键动作。字幕一条一条落定，不让食物和字卡同时抢读。",
            ),
        },
    ),
    (
        "garment",
        "穿搭工艺",
        "服装 衬衫 衣领 面料 走线 穿搭 衣服",
        {
            "punch": (
                "衣领走线点题",
                1.2,
                12,
                "rounded",
                "从整件位置引导到可见衣领或走线",
                "先给整件定位，再推到已核对的衣领/走线焦点。换装、转身过程保持连贯，不以急推伪造垂感或显瘦效果。",
            ),
            "dual": (
                "整件与织纹同帧",
                1.7,
                20,
                "rounded",
                "让整件廓形和面料细节有同时可认的参照",
                "全貌与同帧细节分主次；高倍前检查原始清晰度。口播读到面料时留看，字幕不挤压衣领，不把纹理当成纤维成分证明。",
            ),
            "portal": (
                "衣物斜面陈列",
                1.0,
                24,
                "diagonal",
                "用轮廓展开交代服装的整体形态",
                "斜面从已核对衣物焦点展开，完成后完整留看。穿着动作期不开遮罩，不合成未实拍的上身效果。",
            ),
        },
    ),
    (
        "home",
        "家居布局",
        "家居 收纳 盒体 抽屉 分区 收纳盒 小户型",
        {
            "punch": (
                "收纳焦点轻推",
                1.15,
                18,
                "rounded",
                "先认出家居物件，再引导到真实分区",
                "把推进落在文稿点名的盒体/分区；空间关系看清后回位。开合、放入过程完整展示，不补造容量或承重。",
            ),
            "dual": (
                "整体与分区同步",
                1.5,
                22,
                "rounded",
                "整体帮助定位，细节说明分区在哪里",
                "两个窗口同步播放，整体始终可识别；下窗不做假尺寸刻度。开抽屉与物品放入时恢复完整单窗，配音说完再接下一镜。",
            ),
            "portal": (
                "家居空间柔展",
                1.0,
                30,
                "rounded",
                "从商品局部展开到所在空间",
                "慢于活力展示的展开只做一次落定，随后保留空间关系。稳定素排字幕，避免每句都推镜；不造清洁或收纳前后对比。",
            ),
        },
    ),
    (
        "tool",
        "工具观察",
        "工具 五金 螺丝刀 刀头 握柄 维修 工装",
        {
            "punch": (
                "工具接口定点",
                1.22,
                9,
                "rounded",
                "把注意力一次引到真实工具接口",
                "完整认出工具后再快速推到已核对接口，落定留看，不震屏。装卸、旋转、通电过程不开动效，不宣称未实测的效率。",
            ),
            "dual": (
                "工具整体与刀头",
                1.75,
                14,
                "rounded",
                "整体保留方向，局部说明刀头与握柄关系",
                "局部只是同帧放大，不画虚假结构或数值。字幕读到刀头再展开；操作中单窗留看，不能用两帧拼成性能比较。",
            ),
            "portal": (
                "工具轮廓展开",
                1.0,
                20,
                "diagonal",
                "以明确轮廓快速介绍工具外观",
                "斜面展开后稳定展示全貌，标题短促落定。实拍没有的机械结构不补绘；规格和安全说明须另外有来源。",
            ),
        },
    ),
]
for _category, _goal, _terms, _variants in _CATEGORY_ROWS:
    for _kind, (_name, _zoom, _frames, _shape, _shot_goal, _instruction) in _variants.items():
        _recipe = {
            "punch": "media-punch-in",
            "dual": "detail-dual-window",
            "portal": "product-shape-reveal",
        }[_kind]
        _id = (
            ("bottle" if _category == "beauty" and _kind == "dual" else _category)
            + "-"
            + _kind
            + "-v1"
        )
        CARDS[_id] = {
            "id": _id,
            "name": _name,
            "recipe": _recipe,
            "keywords": _terms.split(),
            "shot_goal": _shot_goal,
            "voice_caption_rule": "画面变化跟随已确认口播字锚点，字幕保持稳定；动作句优先完整留看，数字/术语仍需听核。",
            "prompt": "镜头目的："
            + _shot_goal
            + "。画面编排："
            + _instruction
            + " 听读配合：画面只在语义点做一次主变化，字幕保持独立稳定。 "
            + INSTRUCTIONS[_recipe],
            "source": dict(SHOTCRAFT if _kind == "punch" else PHOTO),
            "adaptation": "本项目原创品类适配；从既有参考方法编排，不复制商品资产或推断功效",
            "presentation": {"zoom": _zoom, "travel_frames": _frames, "shape": _shape},
            "requirements": [
                "有使用权的同款商品画面",
                "短边至少720像素",
                "人工核对焦点、裁切和动作保护区间",
                _goal + "只讲实拍可见内容；功能、规格与使用结论需另有依据",
            ],
        }


for _id, _name, _recipe, _terms, _zoom, _frames, _source_id, _group in [
    (
        "type-mask-clean-v1",
        "字形商品开场 · 精致",
        "product-type-mask",
        "字形 精致 克制 冲击",
        28,
        30,
        "text-as-mask",
        "opening",
    ),
    (
        "type-mask-bold-v1",
        "字形商品开场 · 鲜明",
        "product-type-mask",
        "字形 大胆 运动 活力 冲击",
        36,
        24,
        "text-as-mask",
        "opening",
    ),
    (
        "comic-panels-soft-v1",
        "同帧分区解释 · 柔和",
        "same-frame-panels",
        "分屏 细节 解释 日常",
        1.15,
        16,
        "panel-grid-moves",
        "rhythm",
    ),
    (
        "comic-panels-bold-v1",
        "同帧分区解释 · 利落",
        "same-frame-panels",
        "分屏 运动 年轻 活力",
        1.28,
        10,
        "panel-grid-moves",
        "rhythm",
    ),
]:
    _source = {
        **SHOTCRAFT,
        "url": "https://raw.githubusercontent.com/Vincentwei1021/video-shotcraft/"
        + SHOTCRAFT["commit"]
        + "/references/shots/"
        + _group
        + "/"
        + _source_id
        + ".md",
        "local_reference": "vendor/video-shotcraft/2026-10-full/references/shots/"
        + _group
        + "/"
        + _source_id
        + ".md",
    }
    _prompt = (
        "已确认摘句成为画面字形窗口，真实商品在字形内继续播放，随后展开至清楚全画幅。底层保留同帧，避免空白或丢失商品；字幕独立稳定。不是换产品，也不把文字做成商品图案。"
        if _recipe == "product-type-mask"
        else "同一实拍同一时刻，先保留整体，再用两侧斜分区展示同帧局部并合拢。标明同帧取景，不冒充三个机位或效果对比；动作段完整单窗。"
    )
    CARDS[_id] = {
        "id": _id,
        "name": _name,
        "recipe": _recipe,
        "keywords": _terms.split(),
        "prompt": _prompt,
        "shot_goal": "借观看结构解释真实商品，不新增事实",
        "voice_caption_rule": "已确认摘句入场，字幕保持稳定；动作保护时不叠加",
        "source": _source,
        "adaptation": "本项目原创竖屏实拍适配，区别于上游UI样例",
        "presentation": {"zoom": _zoom, "travel_frames": _frames, "shape": "rounded"},
        "requirements": [
            "有使用权的同款高清实拍",
            "短边至少720像素",
            "人工核对焦点、字形与动作完整性",
        ],
    }


# Finite adaptations of three additional pinned source cards. Existing records
# stay immutable; real media is never relit, replaced, or treated as SKU evidence.
for _prefix, _recipe, _source_id, _group, _name, _terms, _prompt in [
    (
        "hero",
        "product-hero-stage",
        "spotlight-hero-card",
        "opening",
        "商品主角登场",
        "质感 自然 高级 精致 食品 水果 鲜橙 厨房 日常 年轻 外观",
        "真实商品持续可见，外部舞台聚焦，实拍窗口短程靠近后落定留看再回到全幅。不压暗商品、不伪造灯光、悬浮或新角度；字幕独立。",
    ),
    (
        "relay",
        "product-explain-relay",
        "word-relay-filmstrip",
        "typography",
        "讲解摘句接力",
        "讲解 理性 专业 严谨 测评 细节 食品 水果 鲜橙 厨房 日常 年轻",
        "同一实拍连续播放，仅让已确认稿件的至多两条完整短句按字级锚点依次接力（含限定，不截断长句），先退后进，不重叠。旁边不是新证据或多机位，不新增数字与结论；动作段关闭。",
    ),
    (
        "brand",
        "product-brand-snap",
        "brand-frame-snap",
        "effects",
        "品牌画框落位",
        "年轻 活力 生活 日常 厨房 食品 水果 鲜橙 清楚 自然 撞色",
        "用品牌色边框短程长出，完整实拍始终在框内原速播放；停稳后让出商品画面。只包装画面，不换商品颜色、不闪白、不暗示模式或功效比较。",
    ),
]:
    for _variant, _zoom, _frames in [("soft", 1.06, 18), ("bold", 1.14, 10)]:
        _key = f"{_prefix}-{_variant}-v1"
        CARDS[_key] = {
            "id": _key,
            "name": _name + (" · 柔和" if _variant == "soft" else " · 利落"),
            "recipe": _recipe,
            "keywords": (
                _terms + (" 克制 温柔 安静" if _variant == "soft" else " 动感 大胆 冲击")
            ).split(),
            "prompt": _prompt,
            "shot_goal": "用可见实拍解释外观和结构，不新增商品事实",
            "voice_caption_rule": "摘句跟随人声字锚点，稳定字幕留在独立层；动作段完整留看",
            "source": {
                **SHOTCRAFT,
                "url": "https://raw.githubusercontent.com/Vincentwei1021/video-shotcraft/"
                + SHOTCRAFT["commit"]
                + "/references/shots/"
                + _group
                + "/"
                + _source_id
                + ".md",
                "local_reference": "vendor/video-shotcraft/2026-10-full/references/shots/"
                + _group
                + "/"
                + _source_id
                + ".md",
            },
            "source_card_id": _source_id,
            "adaptation": "本项目有限实拍适配；不执行上游代码，不冒充原卡完整3D效果",
            "presentation": {"zoom": _zoom, "travel_frames": _frames, "shape": "rounded"},
            "requirements": [
                "有使用权的同款高清实拍",
                "短边至少720像素",
                "核对焦点、语义字锚点及动作保护",
            ],
        }


for _prefix, _recipe, _source, _group, _name, _prompt, _terms in [
    (
        "detail-bracket",
        "product-detail-bracket",
        "scan-bracket-sweep",
        "effects",
        "商品细节括号",
        "实拍持续原速，四角依次落在人工设置的焦点处，引导观看后退出。只标注文稿焦点，不假装模型正在检测、扫描或测量商品，不改变颜色或源时点。",
        "细节 纹理 果皮 切面 瓶口 接口 结构 耳罩",
    ),
    (
        "fact-row",
        "product-fact-row",
        "row-embed",
        "ui-entrance",
        "来源原文信息行",
        "完整引用当前确认事实的短句以一行信息卡落定，数值原样静态显示，保留价格期限与限定；不截句、不计数增长、不伪造图表或口径。未核对来源或超长时关闭强调，完整字幕仍保留。",
        "数据 参数 规格 销售 价格 说明 原文",
    ),
]:
    for _variant, _travel in [("soft", 18), ("bold", 10)]:
        _key = _prefix + "-" + _variant + "-v1"
        CARDS[_key] = {
            "id": _key,
            "name": _name + (" · 柔和" if _variant == "soft" else " · 利落"),
            "recipe": _recipe,
            "keywords": _terms.split(),
            "prompt": _prompt,
            "shot_goal": "以真实画面和完整来源解释商品，不新增结论",
            "voice_caption_rule": "跟随已核对人声锚点，字幕独立，动作全窗口避让",
            "source": {
                **SHOTCRAFT,
                "url": "https://raw.githubusercontent.com/Vincentwei1021/video-shotcraft/"
                + SHOTCRAFT["commit"]
                + "/references/shots/"
                + _group
                + "/"
                + _source
                + ".md",
                "local_reference": "vendor/video-shotcraft/2026-10-full/references/shots/"
                + _group
                + "/"
                + _source
                + ".md",
            },
            "source_card_id": _source,
            "adaptation": "项目有限实拍适配，不执行上游UI代码",
            "presentation": {
                "zoom": 1.0 if _variant == "soft" else 1.12,
                "travel_frames": _travel,
                "shape": "rounded",
            },
            "requirements": [
                "有使用权的同款高清素材",
                "短边至少720像素",
                "核对焦点；数据/销售需要完整事实原文及有效条件",
            ],
        }


def card_record(card_id):
    card = copy.deepcopy(CARDS[card_id])
    card["version"] = VERSION
    card["digest"] = hashlib.sha256(
        json.dumps(card, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return card


def usable_media(asset):
    meta = asset.get("metadata") or {}
    if isinstance(meta, str):
        meta = json.loads(meta)
    return (
        asset.get("kind") in ("video", "image")
        and min(meta.get("width", 0), meta.get("height", 0)) >= 720
    )


def hits(text, terms):
    result = []
    for term in terms:
        if any(
            not re.search(
                r"(?:不要|避免|不喜欢|不希望|不)\s*$", text[max(0, m.start() - 5) : m.start()]
            )
            for m in re.finditer(re.escape(term), text)
        ):
            result.append(term)
    return result


def context_fields(job, brief):
    return {
        "商品": job["title"] + " " + job["script"],
        "类别": brief["category"],
        "人群": brief["audience"],
        "气质": brief["tone"],
        "目的": {
            "showcase": "商品展示外观",
            "recommendation": "日常生活种草",
            "review": "理性测评",
            "narrated": "清楚说明讲解",
        }.get(brief["format"], ""),
    }


def evidence_for(card_id, job, brief):
    card = card_record(card_id)
    card["matched_inputs"] = {
        label: hits(value, card["keywords"]) for label, value in context_fields(job, brief).items()
    }
    card["basis"] = "frozen_job_brief_and_script_not_new_product_evidence"
    return card


def match_direction(job, brief, style):
    fields = context_fields(job, brief)
    weights = {"商品": 12, "类别": 6, "人群": 8, "气质": 10, "目的": 2}
    preferred = (
        "media-punch-in"
        if style in ("social", "kinetic", "collage")
        else "detail-dual-window"
        if style in ("lab", "evidence", "bauhaus")
        else "product-shape-reveal"
    )
    visuals = [a for a in job["assets"] if a["kind"] in ("image", "video")]
    ready = any(usable_media(a) for a in visuals)
    ranked = []
    for index, key in enumerate(CARDS):
        card = card_record(key)
        matched = {label: hits(value, card["keywords"]) for label, value in fields.items()}
        score = sum(weights[k] * len(v) for k, v in matched.items())
        card.update(
            matched_inputs=matched,
            score=score,
            status="conditional" if ready else "blocked",
            missing=[] if ready else ["请补充短边至少720像素的授权商品画面；不以图形代替实拍动作"],
        )
        ranked.append((score, -index, card))
    languages = BASE_MEDIA_RECIPES
    if hits(brief["tone"], ["冲击", "大胆", "动感", "分屏", "字形"]):
        languages = {"product-type-mask", "same-frame-panels", "detail-dual-window"}
        preferred = (
            "product-type-mask"
            if style in ("editorial", "cinema", "kinetic")
            else "same-frame-panels"
            if style in ("social", "quiet", "collage")
            else "detail-dual-window"
        )
    # Three languages only; extra manual choices do not silently expand a saved board.
    selected = []
    for recipe in [preferred, *sorted(languages - {preferred})]:
        selected.append(
            max((r for r in ranked if r[2]["recipe"] == recipe), key=lambda r: r[:2])[2]
        )
    return {
        "version": VERSION,
        "catalog_revision": CATALOG_REVISION,
        "cards": selected,
        "method": "本机有限词表加权匹配；风格家族区分三种主画面语言，商品/人群/气质确定配方变体。非审美或效果预测",
        "choices": [card_record(k) for k in CARDS],
    }


def select_product_directions(job, brief, options):
    """Exactly three executable, distinct visual languages; no reference-only card.

    Family preference and explicit keyword evidence determine a finite score.
    A frozen shot stores the selected version; revisions never rerun this selector.
    """
    weights = {"商品": 12, "类别": 6, "人群": 8, "气质": 10, "目的": 2}
    families = {
        "premium": ["product-hero-stage", "product-shape-reveal", "product-type-mask"],
        "demo": ["product-explain-relay", "detail-dual-window", "same-frame-panels"],
        "lifestyle": ["product-brand-snap", "media-punch-in", "same-frame-panels"],
    }
    # An explicit visual request takes precedence over generic SKU vocabulary.
    if hits(brief["tone"], ["字形"]):
        families["premium"] = ["product-type-mask"]
    if hits(brief["tone"], ["分屏"]):
        families["lifestyle"] = ["same-frame-panels"]
    if hits(brief["tone"], ["字形", "分屏"]):
        families["demo"] = ["detail-dual-window"]
    ready = any(usable_media(a) for a in job["assets"])
    selected, used = [], set()
    for option in options:
        candidates = []
        for index, key in enumerate(CARDS):
            card = evidence_for(key, job, brief)
            recipe = card["recipe"]
            if recipe not in families[option["family"]] or recipe in used:
                continue
            parts = {k: weights[k] * len(v) for k, v in card["matched_inputs"].items()}
            preference = 18 - 6 * families[option["family"]].index(recipe)
            card.update(
                score_breakdown={**parts, "风格家族": preference},
                score=sum(parts.values()) + preference,
                status="conditional" if ready else "blocked",
                missing=[] if ready else ["请补充短边至少720像素的授权商品画面"],
                product_adaptation={
                    "product": job["title"],
                    "audience": brief["audience"],
                    "tone": brief["tone"],
                    "instruction": card["prompt"],
                    "boundary": "仅编排真实素材与已确认稿件；不是商品识别、功效或吸引力证明",
                },
            )
            candidates.append((card["score"], -index, card))
        card = max(candidates, key=lambda r: r[:2])[2]
        used.add(card["recipe"])
        selected.append(card)
    for option, primary in zip(options, selected, strict=True):
        option["selected_card"] = copy.deepcopy(primary)
        option["prompt_direction"] = {
            "version": VERSION,
            "catalog_revision": "product-selection-v4",
            "cards": [primary] + [copy.deepcopy(c) for c in selected if c["id"] != primary["id"]],
            "method": "商品/类别/人群/气质/目的加权＋风格家族偏好，选出三个不同且已适配的镜头语言；分数不是效果预测。首卡落实本方向，另两卡可逐镜改选。",
            "choices": [card_record(k) for k in CARDS],
        }
    return options


def apply_prompts(rows, lines, durations, assets, direction, *, job=None):
    if direction.get("mix_policy") == "semantic-mix-v1":
        from .semantic_mix import apply_mix

        return apply_mix(
            rows, lines, durations, assets, direction, job or {"script": "\n".join(lines)}
        )

    from .production_direction import ACTION

    result = copy.deepcopy(rows)
    primary = direction["cards"][0]
    counts = Counter()
    for i, row in enumerate(result):
        if (
            i == len(rows) - 1
            or ACTION.search(lines[i])
            or re.search("戴到|戴在|合拢|切开|切片|切下|挤出|剥开", lines[i])
        ):
            row.update(shot_recipe="none", transition="cut")
            row["motion_plan"]["prompt_card"] = None
            continue
        card = primary
        if not usable_media(assets[i]) or durations[i] < (
            2.8
            if card["recipe"] == "media-punch-in"
            else 2.8
            if card["recipe"] in ("detail-dual-window", "same-frame-panels")
            else 1.8
        ):
            row["reason"] += "；Prompt素材/时长不足，保留基础编排并人工补充"
            continue
        limit = (
            min(row["motion_plan"]["repeat_limit"], 1)
            if card["recipe"] in ("product-type-mask", "same-frame-panels")
            else row["motion_plan"]["repeat_limit"]
        )
        if counts[card["recipe"]] >= limit:
            row.update(shot_recipe="none", transition="cut")
            row["motion_plan"]["prompt_card"] = None
            row["reason"] += "；Prompt达到重复上限，留看商品"
            continue
        counts[card["recipe"]] += 1
        row.update(shot_recipe=card["recipe"], transition="cut")
        row["motion_plan"]["prompt_card"] = card["id"]
        row["reason"] += "；Prompt：" + card["name"] + "，焦点与商品仍待人工核对"
    return result
