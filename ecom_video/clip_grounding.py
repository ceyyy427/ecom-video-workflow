"""Conservative visible-context requirements, independent of a model's editorial score.

This finite bilingual vocabulary is not a general semantic parser. Only explicit
mentions become requirements; observations remain fallible keyframe evidence.
No filenames, product facts, manual roles or model ranking reasons count as proof.
"""

import re

VERSION = "visible-context-v2"
# Keep objects separate: a notebook computer is not evidence of a paper notebook;
# a stone display plinth/counter is not automatically an office desk.
VOCABULARY = {
    "desk": ("桌面", r"桌面|桌边|桌上|桌旁|书桌|办公桌|工作台|木桌|桌子|\bdesk\b"),
    "book": (
        "书本",
        r"书本|书籍|书页|记事本|笔记本(?!电脑)|\bbooks?\b|\bnotebook(?!\s*computer)\b",
    ),
    "computer": ("电脑", r"笔记本电脑|电脑|计算机|\blaptop\b|\bcomputer\b"),
    "plant": ("绿植", r"绿植|盆栽|植物|\bplants?\b"),
    "kitchen": ("厨房", r"厨房|灶台|厨台|\bkitchen\b"),
    "outdoor": ("户外", r"户外|室外|露营|\boutdoors?\b|\bcamping\b"),
    "bag": ("包袋", r"背包|帆布包|手提包|手提袋|挎包|\bbackpack\b|\btote\b"),
    "cup": (
        "杯子",
        r"杯子|水杯|咖啡杯|马克杯|保温杯|随行杯|玻璃杯|茶杯|陶瓷杯|高脚杯|\bmug\b|\bcup\b",
    ),
    "lid": ("杯盖", r"杯盖|瓶盖|盖子|\blid\b"),
    "opening": ("开口", r"开口|孔洞|孔口|\bopening\b|\bhole\b"),
    "handle": ("把手", r"把手|手柄|\bhandle\b"),
    "pour": ("倒入动作线索", r"倒入|倒水|注水|倾倒|倒咖啡|\bpour(?:ing|s)?\b"),
    "headphone": ("耳机", r"耳机|\bhead(?:phones?|sets?)\b"),
    "earcup": ("耳罩", r"耳罩|耳垫|\bear\s*(?:cups?|pads?)\b"),
    "headband": ("头梁", r"头梁|\bheadband\b"),
    "bottle": ("瓶身", r"瓶子|瓶身|瓶口|滴管瓶|精华瓶|\bbottles?\b"),
    "dropper": (
        "滴管",
        r"滴管(?!瓶|盖)|\bdroppers?\b(?![\s-]*(?:bottles?|caps?|lids?))|\bpipettes?\b",
    ),
}
NEGATIVE = re.compile(
    r"没有|没见|未见|不见|看不到|未出现|不含|不在|不要|并非|不是|而非|无需|不需要|\bno\b|\bwithout\b|\bnot\b",
    re.I,
)
UNCERTAIN = re.compile(
    r"可能|似乎|或许|看不清|无法判断|不确定|疑似|\bmaybe\b|\bpossibly\b|\bunclear\b|\buncertain\b",
    re.I,
)
# Affirmative transitions end the scope of a preceding rejection, including
# unpunctuated copy such as “不要书本只展示杯盖”.
CLAUSES = re.compile(r"[，。；！？,;.!?\n]+|只(?:展示|看|保留)|但是|但|不过|\bonly\b|\bbut\b", re.I)
PREDICATE_NEGATIVE = re.compile(
    r"^\s*(?:(?:并|也)?(?:没有出现|没出现|未出现|未见|不存在|不在|不可见|看不见|缺失)|"
    r"(?:(?:is|are)\s+)?(?:not\s+(?:visible|present|shown)|absent)\b)",
    re.I,
)


def mentions(text):
    positive, negative, doubtful = {}, set(), set()
    for clause in CLAUSES.split(text):
        for key, (label, pattern) in VOCABULARY.items():
            for found in re.finditer(pattern, clause, re.I):
                prefix = clause[max(0, found.start() - 12) : found.start()]
                if NEGATIVE.search(prefix) or PREDICATE_NEGATIVE.search(clause[found.end() :]):
                    negative.add(key)
                elif UNCERTAIN.search(clause):
                    doubtful.add(key)
                else:
                    positive.setdefault(
                        key, {"label": label, "quote": clause.strip()[:200], "term": found.group()}
                    )
    return positive, negative, doubtful


def requirements(line):
    positive, negative, doubtful = mentions(line)
    return {
        "required": sorted(set(positive) - negative - doubtful),
        "excluded": sorted(negative),
        "ambiguous": sorted(doubtful),
        "version": VERSION,
    }


def assess(line, candidate):
    need = requirements(line)
    observation = candidate["observation"]
    text = "\n".join(
        [
            observation.get("description", ""),
            *observation.get("subjects", []),
            *observation.get("actions", []),
        ]
    )
    visible, negative, doubtful = mentions(text)
    # Explicit uncertainty about an object cannot be repaired by a separate subject tag.
    unknown, absent, doubt = mentions(observation.get("uncertainty", ""))
    negative.update(absent)
    doubtful.update(unknown)
    doubtful.update(doubt)
    # Dense, reference-bound flow evidence supersedes a coarse two-frame omission.
    if any(e.get("kind") == "pour" for e in candidate.get("motion_check", {}).get("events", [])):
        visible["pour"] = {
            "label": "倒入动作线索",
            "quote": "连续抽样帧可见液流",
            "term": "液流时序",
        }
        negative.discard("pour")
        doubtful.discard("pour")
    supported = set(visible) - negative - doubtful
    missing = [key for key in need["required"] if key not in supported]
    conflicts = [key for key in need["excluded"] if key in supported]
    return {
        **need,
        "matched": [{"key": k, **visible[k]} for k in need["required"] if k in supported],
        "missing": [VOCABULARY[k][0] for k in missing],
        "conflicts": [VOCABULARY[k][0] for k in conflicts],
        "eligible": not missing and not conflicts and not need["ambiguous"],
    }


def explain_missing(line, index):
    need = requirements(line)
    labels = [VOCABULARY[k][0] for k in need["required"] + need["ambiguous"]]
    return f"第{index}镜画面要求「{'、'.join(labels) or '排除指定场景'}」缺少明确识别依据；请补充/核对素材，或关闭自动选段后人工安排。"
