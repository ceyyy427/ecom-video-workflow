from ecom_video.captions import phrases


def test_delivery_pause_paging_does_not_show_next_clause_early_or_lose_text():
    text = "袖口贴手腕下摆想收紧"
    words = [
        {
            "text": c,
            "start": i * 0.12 + (1.5 if i >= 5 else 0),
            "end": i * 0.12 + 0.1 + (1.5 if i >= 5 else 0),
            "anchored": i != 4,
        }
        for i, c in enumerate(text)
    ]
    legacy = phrases(text, words)
    assert len(legacy) == 1
    from ecom_video.captions import pause_phrases

    pages = pause_phrases(text, words)
    assert [p["text"] for p in pages] == ["袖口贴手腕", "下摆想收紧"]
    assert pages[0]["end"] == words[4]["end"]
    assert pages[1]["start"] == words[5]["start"]
    assert words[4]["anchored"] is False


def test_pause_paging_preserves_numeric_punctuation_and_spaces():
    from ecom_video.captions import pause_phrases

    text = "ECP33.21 白色，先看外观。"
    chars = [c for c in text if c.isalnum()]
    words = [
        {
            "text": c,
            "start": i * 0.1 + (1 if i >= 9 else 0),
            "end": i * 0.1 + 0.08 + (1 if i >= 9 else 0),
        }
        for i, c in enumerate(chars)
    ]
    normal = phrases(text, words)
    result = pause_phrases(text, words)
    assert "".join(p["text"] for p in result) == "".join(p["text"] for p in normal)
    assert any("33.21" in p["text"] for p in result)
