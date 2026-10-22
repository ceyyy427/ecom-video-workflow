def sample():
    text = "袖口贴着手腕，下摆想收紧，拉一下就行。"
    return {
        "text": text,
        "headline": "收紧",
        "style": "cinema",
        "brand": {"subtitle_size": 76, "accent": "#ffda73"},
        "frames": 120,
        "words": [
            {"text": c, "start": i * 0.2, "end": (i + 1) * 0.2, "anchored": c != "想"}
            for i, c in enumerate(c for c in text if c.isalnum())
        ],
    }


def test_short_phrases_use_true_boundaries_and_preserve_every_word():
    from ecom_video.client_finish import client_captions

    p = sample()
    result = client_captions(p)
    assert [c["text"] for c in result] == ["袖口贴着手腕", "下摆想收紧", "拉一下就行"]
    assert result[1]["start"] == 1.2 and result[1]["end"] == 2.2
    assert "".join(c["text"] for c in result) == "".join(w["text"] for w in p["words"])
    assert all(c["basis"] == "verified_phrase_boundaries" for c in result)


def test_uncertain_edge_and_nonmatching_transcript_never_fabricate_times():
    from ecom_video.client_finish import client_captions

    p = sample()
    p["words"][0]["anchored"] = False
    assert client_captions(p) is None
    p = sample()
    p["words"][0]["text"] = "错"
    assert client_captions(p) is None


def test_sku_wrap_does_not_split_name_or_change_phrase_clock():
    from ecom_video.client_finish import protect_labels
    from ecom_video.subtitle_layout import layout_captions

    p = sample()
    p["protectedTerms"] = ["诺诗兰山甲LT"]
    text = "看看这件藏蓝的诺诗兰山甲LT"
    captions = layout_captions([{"text": text, "start": 0.2, "end": 3.4}], 76, "#fff")
    result = protect_labels(p, captions)
    assert result[0]["lines"] == ["看看这件藏蓝的", "诺诗兰山甲LT"]
    assert result[0]["text"] == text
    assert result[0]["start"] == 0.2 and result[0]["end"] == 3.4


def test_long_clause_keeps_existing_paging_without_losing_text_or_clock():
    from ecom_video.captions import phrases
    from ecom_video.visual_finish import prepare_visuals

    p = sample()
    p.update(
        text="这件外套的领口袖口口袋下摆都可以通过近景看清楚出门之前先看一遍实拍再结合自己的穿搭习惯选择喜欢的颜色",
        frames=600,
        voiceStart=0,
        voiceEnd=15,
        clientPresentation=True,
    )
    p["words"] = [
        {"text": c, "start": i * 0.2, "end": (i + 1) * 0.2, "anchored": True}
        for i, c in enumerate(p["text"])
    ]
    expected = phrases(p["text"], p["words"], 0, 15)
    out = prepare_visuals(p)["captions"]
    assert [{k: c[k] for k in ("text", "start", "end")} for c in out] == expected


def test_uncertain_client_edges_keep_original_clock_but_render_white():
    import base64
    import io

    from PIL import Image

    from ecom_video.captions import phrases
    from ecom_video.visual_finish import prepare_visuals

    p = sample()
    p.update(style="editorial", clientPresentation=True, voiceStart=0, voiceEnd=4)
    p["brand"].update(ink="#282721", paper="#f3efe6")
    p["words"][0]["anchored"] = False
    out = prepare_visuals(p)["captions"]
    assert [{k: c[k] for k in ("text", "start", "end")} for c in out] == phrases(
        p["text"], p["words"], 0, 4
    )
    raster = Image.open(io.BytesIO(base64.b64decode(out[0]["image"].split(",")[1])))
    assert {pixel[:3] for pixel in raster.get_flattened_data() if pixel[3] == 255} == {(255, 255, 255)}
