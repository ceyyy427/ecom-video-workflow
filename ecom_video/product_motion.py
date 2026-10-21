"""Measured visual events and voice-anchored ranges; never infer times from prose."""

import itertools
import math
import re

VERSION = "reference-motion-v4"
PATTERNS = {
    "open_lid": r"打开(?:瓶|杯)?盖|拧开(?:瓶|杯)?盖|旋开(?:瓶|杯)?盖|揭开(?:瓶|杯)?盖|开盖|揭盖",
    "close_lid": r"盖上(?:瓶|杯)?盖|合上(?:瓶|杯)?盖|拧紧(?:瓶|杯)?盖|合盖",
    "pour": r"倒(?:水|入|进|出|咖啡|茶)|注水|倾倒",
}


def build_events(samples):
    rows = sorted(samples, key=lambda s: s["time"])
    events, run = [], []

    def flush():
        if len(run) >= 2:
            events.append(
                {
                    "kind": "pour",
                    "start": run[0]["time"],
                    "end": run[-1]["time"],
                    "anchor": run[0]["time"],
                    "evidence": "连续抽样帧可见液流",
                }
            )
        run.clear()

    for s in rows:
        if s["match"] != "same" or s["flow"] != "visible":
            flush()
        else:
            if run and s["time"] - run[-1]["time"] > 1.5:
                flush()
            run.append(s)
    flush()
    for a, b in zip(rows, rows[1:], strict=False):
        if (
            a["match"] != "same"
            or b["match"] != "same"
            or not 0 < b["time"] - a["time"] <= 1.5
            or not (a["handling_lid"] or b["handling_lid"])
        ):
            continue
        kind = {("attached", "detached"): "open_lid", ("detached", "attached"): "close_lid"}.get(
            (a["lid"], b["lid"])
        )
        if kind:
            events.append(
                {
                    "kind": kind,
                    "start": a["time"],
                    "end": b["time"],
                    "anchor": (a["time"] + b["time"]) / 2,
                    "evidence": "手部操作及相邻抽样帧盖体状态变化",
                }
            )
    return sorted(events, key=lambda e: e["start"])


def verified_ranges(samples):
    """Return only adjacent, uniquely identified observations; never extend endpoints."""
    ranges, run = [], []

    def flush():
        if len(run) >= 2:
            ranges.append({"start": run[0], "end": run[-1]})
        run.clear()

    for sample in sorted(samples, key=lambda s: s.get("time", float("inf"))):
        time = sample.get("time")
        if (
            not isinstance(time, (int, float))
            or not math.isfinite(time)
            or time < 0
            or sample.get("match") != "same"
            or sample.get("target_count") != "one"
        ):
            flush()
            continue
        if run and not 0 < time - run[-1] <= 1.5:
            flush()
        run.append(time)
    flush()
    return ranges


def eligible_identity(candidate, constraints):
    if not (constraints.get("strict_product") or constraints.get("action_timing")):
        return True
    check = candidate.get("motion_check") or {}
    bound = bool(
        constraints.get("reference_sha256")
        and check.get("reference_sha256") == constraints["reference_sha256"]
        and check.get("version") == VERSION
    )
    if not bound:
        return False
    if candidate.get("kind") != "video":
        return check.get("identity") == "same"
    # Recompute from observations, never trust a derived flag or overall identity.
    start, end = candidate.get("start"), candidate.get("end")
    return bool(
        isinstance(start, (int, float))
        and isinstance(end, (int, float))
        and start < end
        and any(
            r["start"] <= start <= end <= r["end"]
            for r in verified_ranges(check.get("samples", []))
        )
    )


def voice_anchors(lines, durations, alignment):
    result, offset = [], 0.0
    sentences = (alignment or {}).get("result", {}).get("sentences", [])
    for i, (line, duration) in enumerate(zip(lines, durations, strict=True)):
        words = sentences[i].get("words", []) if i < len(sentences) else []
        chars = [(ch, w) for w in words for ch in w["text"] if ch.isalnum()]
        text = "".join(ch for ch, _ in chars)
        anchors = []
        for kind, pattern in PATTERNS.items():
            for match in re.finditer(pattern, line):
                prefix = re.split(r"[，。；！？,;.!?]", line[: match.start()])[-1]
                if re.search(
                    r"(?:不要|不用|不必|无需|不需要|没有|不|未)(?:手动|再次|再|先|急着|进行)?$",
                    prefix,
                ):
                    continue
                # Require the same token occurrence, not the first homonym elsewhere.
                term = match.group()
                preceding = len(re.findall(re.escape(term), line[: match.start()]))
                found = list(re.finditer(re.escape(term), text))
                occurrence = found[preceding] if preceding < len(found) else None
                selected = chars[occurrence.start() : occurrence.end()] if occurrence else []
                if not selected or not all(w.get("anchored") for _, w in selected):
                    raise ValueError(
                        f"第{i + 1}镜动作词「{term}」没有可靠字级对齐，请调整文稿/配音并重新听核，或关闭动作对齐人工安排"
                    )
                start, end = selected[0][1]["start"] - offset, selected[-1][1]["end"] - offset
                if not -0.04 <= start < end <= duration + 0.04:
                    raise ValueError(f"第{i + 1}镜动作词越过镜头边界，请调整分句")
                anchors.append(
                    {"kind": kind, "start": max(0, start), "end": min(duration, end), "text": term}
                )
        result.append(sorted(anchors, key=lambda a: a["start"]))
        offset += duration
    return result


def action_ranges(candidate, duration, needs):
    if not needs:
        return [{"start": candidate["start"], "actions": []}]
    if candidate["kind"] != "video":
        return []
    events = candidate.get("motion_check", {}).get("events", [])
    groups = [[e for e in events if e["kind"] == n["kind"]][:8] for n in needs]
    result = []
    for selected in itertools.islice(itertools.product(*groups), 64):
        # A later spoken action cannot borrow an earlier or already-consumed event.
        if any(
            a["end"] > b["start"] or a["anchor"] >= b["anchor"]
            for a, b in zip(selected, selected[1:], strict=False)
        ):
            continue
        low, high = candidate["start"], candidate["end"] - duration
        for need, event in zip(needs, selected, strict=True):
            if need["kind"] == "pour":
                low = max(low, max(candidate["start"], event["start"]) - need["start"])
                high = min(high, min(candidate["end"], event["end"]) - need["end"])
            else:
                if event["start"] < candidate["start"] or event["end"] > candidate["end"]:
                    high = -1
                    break
                center = (need["start"] + need["end"]) / 2
                low = max(low, event["end"] - duration, event["anchor"] - center - 0.6)
                high = min(high, event["start"], event["anchor"] - center + 0.6)
        low, high = math.ceil((low - 1e-7) * 30) / 30, math.floor((high + 1e-7) * 30) / 30
        if low > high:
            continue
        # A bounded frame-grid set permits reuse avoidance without breaking action timing.
        preferred = selected[0]["anchor"] - (needs[0]["start"] + needs[0]["end"]) / 2
        middle = round(min(high, max(low, preferred)) * 30) / 30
        for start in sorted({low, middle, high}):
            result.append(
                {
                    "start": start,
                    "actions": [
                        {
                            "kind": n["kind"],
                            "voice_start": n["start"],
                            "voice_end": n["end"],
                            "source_event": e,
                            "screen_start": e["start"] - start,
                            "screen_end": e["end"] - start,
                        }
                        for n, e in zip(needs, selected, strict=True)
                    ],
                }
            )
    return result
