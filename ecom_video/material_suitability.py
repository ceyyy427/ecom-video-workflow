"""Reference-bound sampled editability. This is neither SKU proof nor full-video certification."""

import math
import re

from PIL import Image

VERSION = "material-checks-v1"


def observation_match(line, candidate, index, count):
    """Finite editorial hints only; caller must still enforce reference/range checks."""
    from .clip_grounding import NEGATIVE, PREDICATE_NEGATIVE, UNCERTAIN

    observation = candidate["observation"]
    if not observation.get("usable") or observation.get("uncertainty", "").strip():
        return None
    text = re.sub(r"[，,。.!！\s]", "", line)
    if text in ("看清楚再选择", "看清再选择"):
        return (
            "相关商品整体收尾，非参数证明"
            if index == count - 1 and observation.get("framing") == "whole"
            else None
        )
    match = re.fullmatch(r"(?:先|再)?看看?(杯身|瓶身|外观|轮廓|纹理|耳罩|头梁|接口|旋钮)", text)
    if not match:
        return None
    term = match[1]
    clauses = re.split(r"[，,。；;！!？?\n]", observation.get("description", ""))
    found = [clause for clause in clauses if term in clause]
    if not found or any(
        NEGATIVE.search(c)
        or UNCERTAIN.search(c)
        or PREDICATE_NEGATIVE.search(c[c.index(term) + len(term) :])
        or re.search(r"无|未|不|没|遮挡|模糊|被挡|难辨|难以|缺失|\babsent\b", c, re.I)
        for c in found
    ):
        return None
    return f"{term}见于关键帧描述，仍需人工回看"


def current_appearance(candidate, reference):
    """Early experimental v1 observations lacked permanent-feature evidence."""
    if reference and candidate.get("asset_sha256") == reference:
        return True  # Exact source bytes identify the reference, not a model guess.
    features = {
        "rim_shape",
        "body_shape",
        "base_facets",
        "surface_relief",
        "surface_color",
        "handle_presence",
        "closure_structure",
        "interface_layout",
        "component_layout",
    }
    samples = candidate.get("motion_check", {}).get("samples", [])
    for sample in samples:
        if sample.get("match") != "same":
            continue
        proof = sample.get("appearance_evidence") or {}
        found = proof.get("permanent_features", [])
        if not (
            proof.get("match") == "same"
            and proof.get("uncertainty") == "none"
            and isinstance(found, list)
            and all(isinstance(f, str) for f in found)
            and len(set(found) & features) >= 2
        ):
            return False
    return bool(samples)


class MaterialBudgetExceeded(ValueError):
    pass


def ordered_events(groups, duration):
    """Prune impossible chronology/time spans BEFORE spending the search budget."""
    visits = 0

    def search(index, chosen):
        nonlocal visits
        if index == len(groups):
            yield chosen
            return
        for event in groups[index]:
            visits += 1
            if visits > 10000:
                raise MaterialBudgetExceeded(
                    "动作组合超过本机检查预算，尚不能认定缺素材；请拆分文稿或人工选段"
                )
            if chosen and (
                chosen[-1]["end"] > event["start"] or chosen[-1]["anchor"] >= event["anchor"]
            ):
                continue
            next_events = (*chosen, event)
            if (
                max(e["complete_end"] for e in next_events)
                - min(e["complete_start"] for e in next_events)
                > duration + 0.001
            ):
                continue
            yield from search(index + 1, next_events)

    yield from search(0, ())


def frame_hash(path):
    with Image.open(path) as im:
        pixels = list(im.convert("L").resize((9, 8)).get_flattened_data())
    bits = [pixels[y * 9 + x] > pixels[y * 9 + x + 1] for y in range(8) for x in range(8)]
    return f"{sum(int(b) << i for i, b in enumerate(bits)):016x}"


def visible(sample):
    box = sample.get("bbox", [])
    if not (
        sample.get("match") == "same"
        and sample.get("target_count") == "one"
        and sample.get("visibility") in ("full", "partial")
        and isinstance(box, (list, tuple))
        and len(box) == 4
        and all(isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 1000 for v in box)
    ):
        return False
    x1, y1, x2, y2 = box
    return x2 > x1 and y2 > y1 and (x2 - x1) * (y2 - y1) >= 40000


def visible_ranges(candidate, reference):
    from .product_motion import verified_ranges

    check = candidate.get("motion_check", {})
    if (
        not reference
        or check.get("reference_sha256") != reference
        or check.get("material_checks_version") != VERSION
        or not current_appearance(candidate, reference)
    ):
        return []
    rows = [{**s, "match": "same" if visible(s) else "uncertain"} for s in check.get("samples", [])]
    return verified_ranges(rows)


def complete_events(candidate, action):
    samples = sorted(candidate.get("motion_check", {}).get("samples", []), key=lambda s: s["time"])
    result = []
    for event in candidate.get("motion_check", {}).get("events", []):
        if event.get("kind") != action:
            continue
        low, high = event["start"], event["end"]
        if not low < high:
            continue
        if action == "pour":
            from .product_motion import build_events

            raw = [{**s, "match": "same" if visible(s) else "uncertain"} for s in samples]
            if not any(
                e["kind"] == "pour" and e["start"] == low and e["end"] == high
                for e in build_events(raw)
            ):
                continue
            before = [
                s
                for s in samples
                if 0 < low - s["time"] <= 1.5 and visible(s) and s.get("flow") == "absent"
            ]
            after = [
                s
                for s in samples
                if 0 < s["time"] - high <= 1.5 and visible(s) and s.get("flow") == "absent"
            ]
            if not before or not after:
                continue
            low, high = before[-1]["time"], after[0]["time"]
        elif action in ("open_lid", "close_lid"):
            proof = event.get("temporal_observation", {})
            if not (
                proof.get("same_single_product")
                and proof.get("hand_manipulates_cap")
                and proof.get("visible_before_and_after")
                and proof.get("uncertainty") == "none"
            ):
                continue
            opening = action == "open_lid"
            if proof.get("cap_moves_away_from_mouth") != opening or proof.get(
                "cap_moves_onto_mouth"
            ) != (not opening):
                continue
            if not any(
                a["time"] == low
                and b["time"] == high
                and 0 < high - low <= 1.5
                and visible(a)
                and visible(b)
                and b.get("lid") == ("detached" if opening else "attached")
                for a, b in zip(samples, samples[1:], strict=False)
            ):
                continue
        else:
            # Sparse labels like 'can fold' do not establish a complete action.
            continue
        result.append({**event, "complete_start": low, "complete_end": high})
    return result


def line_windows(candidate, line, duration, needs, reference, used=()):
    from .product_motion import action_ranges
    from .readiness import action_occurrences

    actions = action_occurrences(line)
    if candidate["kind"] == "image":
        check = candidate.get("motion_check", {})
        return (
            [{"start": 0, "actions": []}]
            if not actions
            and check.get("reference_sha256") == reference
            and check.get("material_checks_version") == VERSION
            and current_appearance(candidate, reference)
            and any(visible(s) for s in check.get("samples", []))
            else []
        )
    ranges = visible_ranges(candidate, reference)
    groups = [complete_events(candidate, a) for a in actions]
    if any(not g for g in groups):
        return []
    results = []
    occupied = [u for u in used if u["asset_sha256"] == candidate["asset_sha256"]]
    for span in ranges:
        low, high = (
            max(span["start"], candidate["start"]),
            min(span["end"], candidate["end"]) - duration,
        )
        if low > high + 0.001:
            continue
        for events in ordered_events(groups, duration):
            a = max(low, max((e["complete_end"] - duration for e in events), default=low))
            b = min(high, min((e["complete_start"] for e in events), default=high))
            if a > b + 0.001:
                continue
            a, b = math.ceil(a * 30 - 1e-7) / 30, math.floor(b * 30 + 1e-7) / 30
            if needs:
                windows = action_ranges(
                    {**candidate, "start": a, "end": b + duration}, duration, needs
                )
            else:
                windows = [
                    {"start": t, "actions": []}
                    for t in sorted({a, b, *(u["start"] + u["duration"] for u in occupied)})
                    if a <= t <= b
                ]
            for w in windows:
                if all(
                    w["start"] <= e["complete_start"] and w["start"] + duration >= e["complete_end"]
                    for e in events
                ):
                    w["complete_actions"] = [
                        {
                            "kind": e["kind"],
                            "source_start": e["complete_start"],
                            "source_end": e["complete_end"],
                            "screen_start": e["complete_start"] - w["start"],
                            "screen_end": e["complete_end"] - w["start"],
                        }
                        for e in events
                    ]
                    results.append(w)
    return results


def repeat_report(candidate, duration, used):
    spans, similar = [], False
    start = candidate["start"]
    for previous in used:
        if candidate["asset_sha256"] == previous["asset_sha256"]:
            a, b = (
                max(start, previous["start"]),
                min(start + duration, previous["start"] + previous["duration"]),
            )
            if b > a:
                spans.append((a, b))
        hashes = [
            s.get("frame_hash")
            for s in candidate.get("motion_check", {}).get("samples", [])
            if start <= s["time"] < start + duration
        ]
        old = [
            s.get("frame_hash")
            for s in previous.get("motion_check", {}).get("samples", [])
            if previous["start"] <= s["time"] < previous["start"] + previous["duration"]
        ]
        similar |= any(
            isinstance(h, str)
            and isinstance(k, str)
            and re.fullmatch(r"[0-9a-fA-F]{16}", h) is not None
            and re.fullmatch(r"[0-9a-fA-F]{16}", k) is not None
            and (int(h, 16) ^ int(k, 16)).bit_count() <= 4
            for h in hashes
            for k in old
        )
    merged = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    overlap = sum(b - a for a, b in merged)
    return {
        "overlap_seconds": round(overlap, 4),
        "overlap_ratio": round(overlap / duration, 4),
        "similar_frame_warning": bool(similar),
        "similarity_scope": "sampled_dhash_hint_not_duplicate_action_or_product_identity",
    }


def check_materials(lines, assets, durations=None, constraints=None):
    from .clip_grounding import assess
    from .readiness import action_occurrences as required_actions

    constraints = constraints or {}
    reference = constraints.get("reference_sha256")
    measured = durations is not None
    durations = durations or [round(max(3, min(12, len(line) / 4)), 2) for line in lines]
    visuals = [a for a in assets if a["kind"] != "audio"]
    pool, unknown = [], not bool(reference)
    for asset in visuals:
        analysis = asset["metadata"].get("content_analysis") or {}
        if (
            asset.get("analysis_stale")
            or analysis.get("source_sha256") != asset["sha256"]
            or analysis.get("recognition", "complete") != "complete"
        ):
            unknown = True
            continue
        if constraints.get("reference_only") and asset["sha256"] == reference:
            continue
        for s in analysis.get("segments", [])[:40]:
            motion = s.get("motion_check") or {}
            if (
                motion.get("material_checks_version") != VERSION
                or motion.get("reference_sha256") != reference
            ):
                unknown = True
                continue
            if not s.get("observation", {}).get("usable") or s.get("quality", {}).get("blank"):
                continue
            pool.append(
                {
                    "id": s["id"],
                    "asset_id": asset["id"],
                    "asset_name": asset["name"],
                    "asset_sha256": asset["sha256"],
                    "kind": asset["kind"],
                    "analysis_id": analysis.get("analysis_id"),
                    "segment_id": s["id"],
                    "start": max(s["start"], asset["metadata"].get("source_in", 0))
                    if asset["kind"] == "video"
                    else 0,
                    "end": min(s["end"], asset["metadata"].get("duration", s["end"])),
                    "motion_check": motion,
                    "observation": s["observation"],
                }
            )
    # This is a bounded advisory allocation, not a proof that no assignment exists.
    # Reserve sources that are the sole feasible option for a later specific line.
    feasible = [
        {
            p["asset_sha256"]
            for p in pool
            if assess(line, p)["eligible"] and line_windows(p, line, d, [], reference)
        }
        for line, d in zip(lines, durations, strict=True)
    ]
    intervals = {}
    for p in pool:
        intervals.setdefault(p["asset_sha256"], []).extend(
            [
                (max(p["start"], s["start"]), min(p["end"], s["end"]))
                for s in visible_ranges(p, reference)
            ]
            if p["kind"] == "video"
            else [(0, 15)]
        )
    capacity = 0
    for spans in intervals.values():
        end = -1
        for a, b in sorted(spans):
            if b > max(a, end):
                capacity += b - max(a, end)
            end = max(end, b)
    proven_short = capacity + 0.001 < sum(durations)
    used, rows = [], []
    for i, (line, duration) in enumerate(zip(lines, durations, strict=True)):
        relevant = [p for p in pool if assess(line, p)["eligible"]]
        visible_pool = [
            p
            for p in relevant
            if visible_ranges(p, reference)
            or (p["kind"] == "image" and any(visible(s) for s in p["motion_check"]["samples"]))
        ]
        options, repeated = [], False
        for p in visible_pool:
            for w in line_windows(p, line, duration, [], reference, used):
                span = {**p, "start": w["start"]}
                repeat = repeat_report(span, duration, used)
                if repeat["overlap_seconds"]:
                    repeated = True
                else:
                    options.append((span, repeat))
        options.sort(
            key=lambda pair: (
                sum(
                    durations[j]
                    for j in range(i + 1, len(lines))
                    if feasible[j] == {pair[0]["asset_sha256"]}
                ),
                pair[0]["kind"] != "video",
                pair[1]["similar_frame_warning"],
                pair[0]["start"],
            )
        )
        code = (
            "observed_candidate"
            if options
            else "no_visuals"
            if not visuals
            else "analysis_missing_or_stale"
            if unknown
            else "unrelated_material"
            if not relevant
            else "subject_not_visible"
            if not visible_pool
            else "repeated_range"
            if repeated and proven_short
            else "allocation_needs_review"
            if repeated
            else "action_incomplete"
            if required_actions(line)
            else "duration_short"
        )
        status = (
            "suggestion"
            if options
            else "unknown"
            if code in ("analysis_missing_or_stale", "allocation_needs_review")
            else "gap"
        )
        messages = {
            "observed_candidate": "有同款外观/可见度与连续区间候选，仍需人工回看，非SKU鉴定",
            "no_visuals": "请上传有权使用的商品图片或实拍",
            "analysis_missing_or_stale": "参照图/增强识别缺失或过期，请选择参照并重新识别；未知不视为可制作",
            "unrelated_material": "没有与本句对象/场景对应的实拍，请补拍或调整文稿",
            "subject_not_visible": "主体太小、遮挡、无法确认同款或不在可见连续区间；请补近景/清晰连续实拍",
            "repeated_range": "现有候选会重复已分配的源时间段，请补充不同选段/角度或人工调整",
            "allocation_needs_review": "当前估算分配发生重复，尚不能认定素材不足；按实测配音进一步分配或逐镜人工安排",
            "action_incomplete": "缺少动作前后完整证据或无法装进本句时长；请补连续过程、调整分句或人工安排",
            "duration_short": "主体可见的连续时长不足，请补拍或调整本句时长",
        }
        if options:
            used.append({**options[0][0], "duration": duration})
        rows.append(
            {
                "line": i + 1,
                "text": line,
                "duration": duration,
                "duration_basis": "measured" if measured else "estimated",
                "required_action": next(iter(required_actions(line)), None),
                "required_actions": required_actions(line),
                "status": status,
                "code": code,
                "message": messages[code],
                "candidates": [
                    {
                        "asset_id": p["asset_id"],
                        "name": p["asset_name"],
                        "sha256": p["asset_sha256"],
                        "analysis_id": p["analysis_id"],
                        "source_in": p["start"],
                        "source_end": p["start"] + duration if p["kind"] == "video" else 0,
                        "observation": p["observation"]["description"],
                        "repeat_check": repeat,
                    }
                    for p, repeat in options[:3]
                ],
            }
        )
    return {
        "version": VERSION,
        "material_checks": True,
        "human_review_required": True,
        "lines": rows,
        "gap_count": sum(r["status"] == "gap" for r in rows),
        "unknown_count": sum(r["status"] == "unknown" for r in rows),
        "duration_basis": "measured" if measured else "estimated",
        "scope": "参照绑定的有限抽样、估计分配；不是SKU鉴定、逐帧认证或完整风格可执行保证",
    }


def material_inputs(project):
    settings = project["settings"]
    reference = next(
        (
            a
            for a in project["media"]
            if a["id"] == settings.get("product_reference_id") and a["kind"] == "image"
        ),
        None,
    )
    assets = []
    for a in project["media"]:
        analysis = a.get("analysis") or {}
        assets.append(
            {
                **a,
                "metadata": {
                    **a["metadata"],
                    "source_in": a["source_in"],
                    "content_analysis": analysis.get("result")
                    if analysis.get("status") == "ready"
                    else None,
                },
            }
        )
    return assets, {
        "material_checks": bool(settings.get("material_checks")),
        "reference_sha256": reference["sha256"] if reference else None,
        "reference_only": bool(settings.get("reference_only")),
    }


def fit_summary(report, style_id=None, *, assets=None, constraints=None, format=None):
    from .clip_grounding import mentions

    style_gap = None
    inventory = {"whole": 0, "detail": 0, "context": 0}
    inspection_unknown = False
    if style_id and assets is not None:
        ref = (constraints or {}).get("reference_sha256")
        for asset in assets:
            if asset["kind"] == "audio" or (
                (constraints or {}).get("reference_only") and asset["sha256"] == ref
            ):
                continue
            analysis = asset["metadata"].get("content_analysis") or {}
            if (
                asset.get("analysis_stale")
                or analysis.get("source_sha256") != asset["sha256"]
                or analysis.get("recognition", "complete") != "complete"
            ):
                inspection_unknown = True
                continue
            for segment in analysis.get("segments", [])[:40]:
                candidate = {
                    "kind": asset["kind"],
                    "asset_sha256": asset["sha256"],
                    "motion_check": segment.get("motion_check", {}),
                }
                motion = candidate["motion_check"]
                low = (
                    max(segment["start"], asset["metadata"].get("source_in", 0))
                    if asset["kind"] == "video"
                    else 0
                )
                high = min(segment["end"], asset["metadata"].get("duration", segment["end"]))
                motion = {
                    **motion,
                    "samples": [
                        x
                        for x in motion.get("samples", [])
                        if asset["kind"] == "image" or low <= x["time"] <= high
                    ],
                }
                candidate["motion_check"] = motion
                if (
                    motion.get("material_checks_version") != VERSION
                    or motion.get("reference_sha256") != ref
                ):
                    inspection_unknown = True
                    continue
                if not segment.get("observation", {}).get("usable") or segment.get(
                    "quality", {}
                ).get("blank"):
                    continue
                if not (
                    visible_ranges(candidate, ref)
                    or asset["kind"] == "image"
                    and current_appearance(candidate, ref)
                    and any(visible(x) for x in motion.get("samples", []))
                ):
                    continue
                obs = segment["observation"]
                inventory["whole"] += any(
                    visible(x) and x.get("visibility") == "full" for x in motion["samples"]
                )
                segment_fully_available = asset["kind"] == "image" or (
                    low <= segment["start"] and high >= segment["end"]
                )
                inventory["detail"] += segment_fully_available and obs.get("framing") == "detail"
                text = obs.get("description", "") + "。" + "。".join(obs.get("subjects", []))
                inventory["context"] += segment_fully_available and (
                    obs.get("framing") == "context"
                    or bool(set(mentions(text)[0]) & {"desk", "kitchen", "outdoor"})
                )
        wanted = (
            "detail"
            if style_id in ("lab", "evidence", "bauhaus")
            else "context"
            if style_id in ("quiet", "social", "collage")
            else "whole"
        )
        if inventory[wanted] == 0:
            style_gap = {
                "code": {
                    "detail": "detail_shot_missing",
                    "context": "context_shot_missing",
                    "whole": "whole_shot_missing",
                }[wanted],
                "message": {
                    "detail": "本方向需要对应部位近景；现有候选未观察到可靠细节镜头，可补拍或逐镜人工调整，细节框不能代替近景",
                    "context": "本方向需要商品与使用环境同场的镜头；可补场景实拍或改选整体展示方向",
                    "whole": "本方向需要主体清楚的完整陈列；请补整体画面或人工调整取景",
                }[wanted],
            }
        if style_id == "cinema" and format == "showcase" and report["lines"]:
            durations = [x["duration"] for x in report["lines"]]
            durations[0] = max(5.4, durations[0])
            updated = check_materials(
                [x["text"] for x in report["lines"]], assets, durations, constraints
            )
            updated["duration_basis"] = report.get("duration_basis", "estimated")
            report = updated
            if report["lines"][0]["status"] == "gap":
                style_gap = {
                    "code": "intro_duration_short",
                    "message": "此纯展示方向开场至少5.4秒，现有主体可见区间不足；请补连续实拍或改选其他方向",
                }
    status = (
        "needs_material"
        if report["gap_count"] or style_gap and not inspection_unknown
        else "unknown"
        if report["unknown_count"] or style_gap
        else "possible_with_review"
    )
    return {
        "version": VERSION,
        "status": status,
        "gap_count": report["gap_count"],
        "unknown_count": report["unknown_count"],
        "duration_basis": report.get("duration_basis", "estimated"),
        "can_do": [r["line"] for r in report["lines"] if r["status"] == "suggestion"],
        "missing": [
            {"line": r["line"], "text": r["text"], "code": r["code"], "message": r["message"]}
            for r in report["lines"]
            if r["status"] != "suggestion"
        ],
        "note": "现有素材按文稿与风格镜头需求检查；配音完成后按实测镜长重检。同帧双窗不等于多角度实拍，选定风格不代表素材已齐备。",
        "style_id": style_id,
        "style_gap": style_gap,
        "observed_shot_types": inventory,
    }
