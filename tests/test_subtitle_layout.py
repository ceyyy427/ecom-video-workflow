"""Bounded, local subtitle layout and its existing preview/renderer integration."""

import base64
import io
import json
from pathlib import Path

import pytest
from PIL import Image, ImageFont

from ecom_video.media import digest, font_path


def test_measured_wrap_hard_breaks_and_font_metrics():
    from ecom_video.subtitle_layout import wrap_text

    font = ImageFont.truetype(str(font_path()), 60)
    text, height = wrap_text("Air Pro\n杯口设计与杯身轮廓", 240, str(font_path()), 60)
    assert text.startswith("Air Pro\n")
    assert all(font.getbbox(line)[2] - font.getbbox(line)[0] <= 240 for line in text.splitlines())
    assert height == len(text.splitlines()) * sum(font.getmetrics())


def test_combining_marks_and_punctuation_stay_with_text():
    from ecom_video.subtitle_layout import wrap_text

    text, _ = wrap_text("Cafe\u0301Cafe\u0301Cafe\u0301。", 140, str(font_path()), 60)
    assert "".join(text.splitlines()) == "Cafe\u0301Cafe\u0301Cafe\u0301。"
    assert all(not line.startswith(("\u0301", "。")) for line in text.splitlines())


def test_caption_raster_preserves_content_and_timing_and_fits_safe_area():
    from ecom_video.subtitle_layout import layout_captions

    captions = [{"text": "容量1.5升 浓度0.9% Air Pro", "start": 0.25, "end": 3.75}]
    result = layout_captions(captions, 64, "#ffffff")
    item = result[0]
    assert (item["text"], item["start"], item["end"]) == (captions[0]["text"], 0.25, 3.75)
    assert "1.5" in " ".join(item["lines"]) and "0.9%" in " ".join(item["lines"])
    assert 1 <= len(item["lines"]) <= 2
    assert item["width"] <= 912
    with Image.open(io.BytesIO(base64.b64decode(item["image"].split(",", 1)[1]))) as im:
        assert im.mode == "RGBA" and im.size == (item["width"], item["height"])
        assert im.getbbox() is not None and im.getpixel((0, 0))[3] == 0
    assert captions == [{"text": "容量1.5升 浓度0.9% Air Pro", "start": 0.25, "end": 3.75}]


def test_unreadable_caption_fails_instead_of_truncating_text():
    from ecom_video.subtitle_layout import layout_captions

    with pytest.raises(ValueError, match="字幕.*两行"):
        layout_captions([{"text": "很长的连续字幕" * 80, "start": 0, "end": 5}], 64, "#fff")


def test_existing_style_previews_use_raster_caption_layout(tmp_path, monkeypatch):
    from ecom_video.creative import Brief, recommend
    from ecom_video.remotion_renderer import style_previews

    path = tmp_path / "fixture.png"
    Image.new("RGB", (60, 60), "#bbb").save(path)
    job = {
        "id": "fixture",
        "title": "测试素材",
        "script": "容量1.5升 外观展示",
        "assets": [{"id": "asset", "kind": "image", "path": path.name, "sha256": digest(path)}],
    }
    rec = recommend(job, Brief(format="narrated"))
    rendered = []

    def render(command, **kwargs):
        config = json.loads(Path(command[-1]).read_text())
        rendered.extend(config["shots"])
        for shot in config["shots"]:
            Image.new("RGB", (1, 1)).save(config["outputDir"] + "/" + shot["key"] + ".png")

    monkeypatch.setattr("ecom_video.remotion_renderer.run_checked", render)
    previews = style_previews(job, tmp_path, rec)
    assert len(previews) == 3 and len(rendered) == 3
    assert all(
        shot["props"]["captions"][0].get("image", "").startswith("data:image/png;base64,")
        for shot in rendered
    )
    assert all(url.startswith("/api/jobs/fixture/creative/previews/") for url in previews.values())


def test_render_caption_preparation_retains_verified_phrase_times():
    from ecom_video.captions import phrases
    from ecom_video.subtitle_layout import prepare_captions

    text = "外观清晰，杯身细节"
    words = [
        {"text": char, "start": index * 0.3 + 0.2, "end": index * 0.3 + 0.4}
        for index, char in enumerate(c for c in text if c.isalnum())
    ]
    expected = phrases(text, words, 0, 5)
    props = {
        "text": text,
        "words": words,
        "voiceStart": 0,
        "voiceEnd": 5,
        "style": "lab",
        "brand": {"subtitle_size": 64, "ink": "#282721"},
    }
    actual = prepare_captions(props)
    assert [{k: item[k] for k in ("text", "start", "end")} for item in actual] == expected
    assert props["words"] == words
