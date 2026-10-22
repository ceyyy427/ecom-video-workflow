"""Read-only customer editing clock. Rendered captions are evidence, not predictions."""

import re

from .delivery_revision import member
from .media import digest, safe_path
from .narrato_subtitle_text import decode_subtitle_bytes


def parse_captions(data, duration):
    # NarratoAI's MIT decoder handles BOM, UTF-16 and timestamp separators.
    # Retain our punctuation and timing: never strip decimals or estimate new words.
    text = decode_subtitle_bytes(data).text
    rows = []
    for block in re.split(r"\n\s*\n", text):
        lines = block.strip().splitlines()
        index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if index is None:
            if block.strip():
                raise ValueError("字幕块缺少时间范围")
            continue
        times = re.fullmatch(
            r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})",
            lines[index].strip(),
        )
        if not times:
            raise ValueError("字幕时间格式无效")
        h, m, s, ms, h2, m2, s2, ms2 = map(int, times.groups())
        start, end = h * 3600 + m * 60 + s + ms / 1000, h2 * 3600 + m2 * 60 + s2 + ms2 / 1000
        if max(m, s, m2, s2) >= 60 or not 0 <= start < end <= duration + 0.1:
            raise ValueError("字幕时间超出成片范围")
        rows.append({"start": start, "end": end, "text": "\n".join(lines[index + 1 :])})
        if len(rows) > 5000:
            raise ValueError("字幕条数超出预览上限")
    return rows


def timeline(service, root, pid, job_id=None):
    project = service.get(pid)
    job = member(service, pid, job_id) if job_id else project.get("job")
    result = {
        "job_id": job["id"] if job else None,
        "duration": 0,
        "shots": [],
        "captions": [],
        "caption_status": "not_rendered",
        "warning": None,
        "audio": {},
    }
    if not job or not job.get("storyboard"):
        return result
    board = job["storyboard"]
    start = 0
    for shot in board["shots"]:
        result["shots"].append({**shot, "start": round(start, 6)})
        start += shot["duration"]
    result["duration"] = round(start, 6)
    result["audio"] = {"narration": board.get("narration"), "music_id": board.get("music_id")}
    subtitle = next((a for a in job["artifacts"] if a["kind"] == "subtitles"), None)
    if subtitle:
        try:
            path = safe_path(root, subtitle["path"])
            if path.stat().st_size > 2 * 1024**2 or digest(path) != subtitle["sha256"]:
                raise ValueError("字幕文件与登记版本不一致")
            result["captions"] = parse_captions(path.read_bytes(), start)
            result["caption_status"] = "rendered"
        except (OSError, ValueError):
            result["caption_status"] = "unavailable"
            result["warning"] = "本版字幕无法校验；请查看原字幕文件，不使用估算字幕替代。"
    return result
