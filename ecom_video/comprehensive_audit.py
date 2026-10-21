"""Frozen, located checks with explicit missing coverage; never automated clearance."""

import copy
import html
import json
from difflib import SequenceMatcher

from .audit import audit_script
from .audit_media import normalized
from .creative import signature
from .readiness import check_materials, required_actions


def scene_timeline(snapshot, actual=None):
    position, rows = 0, []
    shots = (snapshot.get("storyboard") or {}).get("shots", [])
    for i, line in enumerate(snapshot["script"].splitlines()):
        duration = shots[i]["duration"] if i < len(shots) else snapshot.get("seconds", 3)
        start, end = position, position + duration
        if actual and i < len(actual):
            start, end = actual[i]["start"], actual[i]["end"]
        rows.append(
            {
                "line": i + 1,
                "text": line,
                "start": start,
                "end": end,
                "shot_id": shots[i].get("shot_id") if i < len(shots) else None,
                "asset_id": shots[i].get("asset_id") if i < len(shots) else None,
            }
        )
        position += duration
    return rows


def build_report(
    jid, snapshot, qc, media, *, output_sha256=None, actual_scenes=None, source_verified=False
):
    report = audit_script(snapshot["script"])
    report.update(
        schema_version=2,
        version="comprehensive-v1",
        job_id=jid,
        snapshot_sha256=signature(snapshot),
        output_sha256=output_sha256,
        human_review_required=True,
        changes_applied=False,
        summary="本机综合预检；已检查、抽样、未知和未覆盖分开记录。没有自动合规放行，仍需人工听核和成片审核。",
    )
    scenes = scene_timeline(snapshot, actual_scenes)
    for f in report["findings"]:
        f.update(source="script", time=scenes[f["line"] - 1]["start"])
    sections = [{"id": "script_rules", "status": "checked", "method": report["rule_version"]}]
    provenance = snapshot.get("provenance")
    report["provenance"] = {
        "product_id": (provenance or {}).get("product_id"),
        "fact_review_id": ((provenance or {}).get("fact_review") or {}).get("id"),
        "script_approval_id": ((provenance or {}).get("script_approval") or {}).get("id"),
        "source_integrity": "verified" if provenance and source_verified else "not_available",
        "semantic_verification": "human_only",
    }
    sections += [
        {
            "id": "source_integrity",
            "status": "checked" if provenance and source_verified else "not_checked",
            "method": "worker已校验来源和素材字节哈希；不证明陈述真实",
        },
        {
            "id": "product_evidence",
            "status": "needs_review",
            "method": "保留事实引用；陈述是否被来源支持仍需人工核对",
        },
    ]
    assets = {a["id"]: a for a in snapshot.get("assets", [])}
    shots = (snapshot.get("storyboard") or {}).get("shots", [])
    for scene, shot in zip(scenes, shots, strict=False):
        a = copy.deepcopy(assets.get(shot["asset_id"]))
        if not a:
            continue
        if isinstance(a["metadata"], str):
            a["metadata"] = json.loads(a["metadata"])
        a["metadata"]["source_in"] = shot.get("source_in", 0)
        analysis = a["metadata"].get("content_analysis")
        if analysis:
            start, end = shot.get("source_in", 0), shot.get("source_in", 0) + shot["duration"]
            analysis["segments"] = [
                {**s, "start": max(start, s["start"]), "end": min(end, s["end"])}
                for s in analysis["segments"]
                if a["kind"] == "image" or min(end, s["end"]) > max(start, s["start"])
            ]
        row = check_materials(
            snapshot["script"].splitlines(), [a], [s["end"] - s["start"] for s in scenes]
        )["lines"][scene["line"] - 1]
        actions = required_actions(scene["text"])
        events = [
            e
            for s in (analysis or {}).get("segments", [])
            for e in s.get("motion_check", {}).get("events", [])
        ]
        low, high = shot.get("source_in", 0), shot.get("source_in", 0) + shot["duration"]
        if actions and not all(
            any(
                e.get("kind") == kind and low <= e.get("start", -1) < e.get("end", -1) <= high
                for e in events
            )
            for kind in actions
        ):
            row.update(
                status="unknown",
                code="action_time_unverified",
                candidates=[],
                message="所选区间没有覆盖全部动作的带时间证据；整段标签不能证明此处发生动作，请逐镜回看",
            )
        scene["material"] = row
        if row["status"] != "suggestion":
            report["findings"].append(
                {
                    "rule_id": "selected_material_review",
                    "source": "material",
                    "severity": "review",
                    "line": scene["line"],
                    "time": scene["start"],
                    "term": row["code"],
                    "reason": row["message"],
                    "suggestion": "逐镜回看，必要时补拍或替换这一镜",
                }
            )
    sections.append(
        {
            "id": "selected_material",
            "status": "needs_review",
            "method": "冻结选段与关键帧观察交集；非逐帧或SKU认证",
        }
    )
    for origin in ("ocr", "asr"):
        value = copy.deepcopy(
            media.get(origin) or {"status": "not_checked", "reason": "本次未运行"}
        )
        sections.append({"id": origin, **value})
        if value["status"] in ("error", "partial"):
            report["findings"].append(
                {
                    "rule_id": "check_unavailable",
                    "source": origin,
                    "severity": "review",
                    "line": 1,
                    "time": 0,
                    "term": origin,
                    "reason": value.get("reason", "部分抽样未完成"),
                    "suggestion": "不要当作检查通过，请人工核对",
                }
            )
        items = (
            [
                {"text": "".join(t["text"] for t in f.get("texts", [])), "time": f["time"]}
                for f in value.get("frames", [])
            ]
            if origin == "ocr"
            else [{"text": w["text"], "time": w["start"]} for w in value.get("words", [])]
        )
        # Join neighboring ASR tokens so a risk phrase split into characters is not missed.
        if origin == "asr" and items:
            text = "".join(x["text"] for x in items)
            cursor, spans = 0, []
            for x in items:
                spans.append((cursor, cursor + len(x["text"]), x["time"]))
                cursor += len(x["text"])
            found = audit_script(text)["findings"]
            items = [{"text": text, "time": 0}]
        else:
            found, spans = [], []
        for item in items:
            for f in found if origin == "asr" else audit_script(item["text"])["findings"]:
                at = item["time"]
                if spans:
                    offset = f["normalized_column"] - 1
                    at = next((t for low, high, t in spans if low <= offset < high), at)
                scene = next((s for s in scenes if s["start"] <= at < s["end"]), scenes[-1])
                report["findings"].append(
                    {
                        **f,
                        "source": origin,
                        "line": scene["line"],
                        "time": at,
                        "original_rule_severity": f["severity"],
                        "severity": "review",
                        "suggestion": "识别结果可能有误，请跳转对应时间核对；" + f["suggestion"],
                    }
                )
        if origin == "asr" and value["status"] == "checked":
            transcript = "".join(w["text"] for w in value.get("words", []))
            expected, observed = normalized(snapshot["script"]), normalized(transcript)
            matcher = SequenceMatcher(None, expected, observed, autojunk=False)
            ratio = matcher.ratio()
            sections[-1].update(transcript=transcript, text_similarity=round(ratio, 4))
            expected_lines = [scene["line"] for scene in scenes for _ in normalized(scene["text"])]
            observed_times = [
                w["start"] for w in value.get("words", []) for _ in normalized(w["text"])
            ]
            differences = [op for op in matcher.get_opcodes() if op[0] != "equal"]
            for _, low, high, a, b in differences[:12]:
                line = expected_lines[min(low, len(expected_lines) - 1)] if expected_lines else 1
                at = observed_times[min(a, len(observed_times) - 1)] if observed_times else 0
                report["findings"].append(
                    {
                        "rule_id": "spoken_script_difference",
                        "source": "asr",
                        "severity": "review",
                        "line": line,
                        "time": at,
                        "term": "口播与确认稿识别差异",
                        "reason": f"确认稿片段「{expected[low:high][:40]}」/识别「{observed[a:b][:40]}」；全稿文字相似度{ratio:.1%}（非准确率）",
                        "suggestion": "听辨术语、数字和否定词；识别也会出错，不自动改稿或批准",
                    }
                )
            sections[-1]["difference_count"] = len(differences)
            sections[-1]["shown_differences"] = min(12, len(differences))
    alignment = snapshot.get("alignment")
    sections += [
        {
            "id": "alignment",
            "status": "checked" if alignment else "not_checked",
            "method": "已保存的本版字锚点及人工听核，不等于最终音轨识别核验",
            "timing_review": (alignment or {}).get("timing_review"),
            "estimated_words": sum(
                not w["anchored"]
                for s in (alignment or {}).get("sentences", [])
                for w in s["words"]
            ),
        },
        {
            "id": "technical",
            "status": "checked" if qc.get("full_decode_passed") else "not_checked",
            "result": qc,
        },
        {
            "id": "rights",
            "status": "not_checked",
            "method": "需人工核对人物、商品、字体、音乐、素材许可",
        },
        {
            "id": "platform_policy",
            "status": "not_checked",
            "method": "本地有限规则未核对平台最新要求或类目资质",
        },
        {
            "id": "visual_semantics",
            "status": "not_checked",
            "method": "OCR不检查裸露、危险行为、商标或全部视觉语义；无自动SKU鉴定",
        },
    ]
    report["coverage"].update(
        ocr=any(s["id"] == "ocr" and s["status"] == "sampled" for s in sections),
        audio_asr=any(s["id"] == "asr" and s["status"] == "checked" for s in sections),
    )
    report.update(sections=sections, scenes=scenes)
    return report


def html_report(report):
    def esc(value):
        return html.escape(str(value), quote=True)

    def code_block(value):
        lines = json.dumps(value, ensure_ascii=False, indent=2).splitlines()
        return (
            "<code>"
            + "<br>".join(
                "<wbr>".join(esc(line[i : i + 24]) for i in range(0, len(line), 24))
                for line in lines
            )
            + "</code>"
        )

    parts = [
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>综合审核报告</title><link rel='stylesheet' href='/static/audit-report.css'></head><body><main>",
        "<h1>综合审核报告 · 待人工确认</h1><p>" + esc(report["summary"]) + "</p>",
        "<p>未检查、抽样或识别失败均不表示通过。</p><p>任务："
        + "<wbr>".join(
            esc(report["job_id"])[i : i + 16] for i in range(0, len(esc(report["job_id"])), 16)
        )
        + "</p><h2>逐镜检查</h2>",
    ]
    for s in report["scenes"]:
        parts += [
            f"<article>第{s['line']}镜 · {s['start']:.2f}–{s['end']:.2f}s<p>{esc(s['text'])}</p></article>"
        ]
    parts.append("<h2>问题定位</h2>")
    for f in report["findings"]:
        parts.append(
            f"<article>第{f['line']}镜 · {f.get('time', 0):.2f}s · {esc(f.get('source', 'script'))}<p>{esc(f['reason'])}</p><p>{esc(f['suggestion'])}</p></article>"
        )
    parts.append("<h2>检查范围与未检查项</h2>")
    for s in report["sections"]:
        parts.append(
            "<details><summary>"
            + esc(s["id"])
            + " · "
            + esc(s["status"])
            + "</summary><p>"
            + esc(s.get("method") or s.get("reason") or s.get("scope") or "")
            + "</p>"
            + code_block(s)
            + "</details>"
        )
    parts.append("</main></body></html>")
    return "".join(parts)
