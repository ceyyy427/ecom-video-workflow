import copy

import pytest
from test_creative_proposals import get_bundle
from test_customer import approve, client, picture, project


def test_preview_specs_preserve_video_and_reject_unknown_identity():
    from ecom_video.creative_preview import preview_specs
    from ecom_video.prompt_catalog import card_record

    asset = {
        "id": "v",
        "kind": "video",
        "role": "product",
        "source_in": 1,
        "sha256": "a" * 64,
        "metadata": {"width": 1080, "height": 1920, "duration": 10},
    }
    p = {"media": [asset], "settings": {}}
    c = {
        "payload": [{"text": "先看", "fact_ids": []}, {"text": "看细节", "fact_ids": ["f"]}],
        "visual_plan": [
            {"kind": "video", "card": card_record("garment-punch-v1")},
            {"kind": "detail", "card": card_record("detail-bracket-soft-v1")},
        ],
    }
    specs = preview_specs(p, c)
    assert [s["asset"]["kind"] for s in specs] == ["video", "video"]
    assert all(s["seconds"] == 3 and s["source_in"] == 1 for s in specs)
    p["settings"] = {"delivery_version": 1, "identity_lock": {"sku": "山甲", "color": "藏蓝"}}
    with pytest.raises(ValueError, match="款式|配色|素材"):
        preview_specs(p, c)


def test_preview_does_not_mutate_script_or_reviews_and_rejects_stale_bundle(tmp_path, monkeypatch):
    from ecom_video import creative_preview

    c = client(tmp_path)
    p = approve(c, picture(c, project(c)))
    bundle = get_bundle(c, p)
    before = copy.deepcopy(p["product"])
    called = []

    def render(root, store, current, proposal, basis):
        called.append(proposal["id"])
        return {
            "key": "a" * 64,
            "duration": 6,
            "muted": True,
            "approval": "none",
            "url": "/preview-fixture",
        }

    monkeypatch.setattr(creative_preview, "create_preview", render)
    req = {
        "revision": p["revision"],
        "product_revision": p["product"]["revision"],
        "basis": bundle["basis"],
        "candidate_id": "overview",
    }
    endpoint = f"/api/customer-projects/{p['id']}/creative-proposals/preview"
    r = c.post(endpoint, json=req)
    assert r.status_code == 200, r.text
    assert r.json()["muted"] and r.json()["approval"] == "none"
    assert c.get(f"/api/products/{p['id']}").json() == before
    newer = c.put(
        f"/api/customer-projects/{p['id']}",
        json={
            "revision": p["revision"],
            "settings": {**p["settings"], "brief": {**p["settings"]["brief"], "tone": "清楚"}},
        },
    ).json()
    assert c.post(endpoint, json={**req, "revision": newer["revision"]}).status_code == 409
    assert called == ["overview"]


def test_preview_cannot_be_returned_as_current_after_inputs_change_during_render(
    tmp_path, monkeypatch
):
    from ecom_video import creative_preview

    c = client(tmp_path)
    p = approve(c, picture(c, project(c)))
    bundle = get_bundle(c, p)

    def racing(root, store, current, proposal, basis):
        with store.transaction() as db:
            db.execute(
                "UPDATE customer_projects SET revision=revision+1 WHERE product_id=?", (p["id"],)
            )
        return {"url": "/old.mp4", "muted": True}

    monkeypatch.setattr(creative_preview, "create_preview", racing)
    r = c.post(
        f"/api/customer-projects/{p['id']}/creative-proposals/preview",
        json={
            "revision": p["revision"],
            "product_revision": p["product"]["revision"],
            "basis": bundle["basis"],
            "candidate_id": "overview",
        },
    )
    assert r.status_code == 409, r.text


def test_preview_emphasis_reuses_full_quote_guard():
    from ecom_video.creative_preview import guarded_motion

    candidate = {
        "payload": [{"text": "仅活动期内满200元减20元，不含运费。", "fact_ids": ["f"]}],
        "source_facts": [{"id": "f", "text": "仅活动期内满200元减20元，不含运费。"}],
    }
    decision = {"recipe": "product-fact-row"}
    out = guarded_motion(candidate, 0, decision)
    assert out["quote"]["text"] == candidate["payload"][0]["text"]
    assert out["suppress_headline"]
    candidate["payload"][0]["text"] = "满200元减20元"
    assert guarded_motion(candidate, 0, decision)["recipe"] == "none"


def test_preview_keeps_non_numeric_conditions_together_even_for_showcase():
    from ecom_video.creative_preview import preview_typography

    line = "本款支持防水功能，但仅限短时小雨，不适用于持续淋雨。"
    props = {
        "text": line,
        "headline": line[:8],
        "style": "editorial",
        "format": "showcase",
        "brand": {"subtitle_size": 60, "ink": "#000000"},
        "words": [],
        "voiceStart": 0,
        "voiceEnd": 3,
    }
    result = preview_typography(props, True)
    assert result["headline"] == ""
    assert result["format"] != "showcase"
    assert len(result["captions"]) == 1
    assert result["captions"][0]["text"] == line
    assert result["captions"][0]["end"] == 3


def test_low_resolution_preview_uses_same_card_fallback_as_production():
    from ecom_video.creative_preview import preview_specs
    from ecom_video.prompt_catalog import card_record

    p = {"media": [{"kind": "image", "metadata": {"width": 160, "height": 240}}], "settings": {}}
    candidate = {
        "payload": [
            {"text": "开头", "fact_ids": []},
            {"text": "细节", "fact_ids": ["f"]},
            {"text": "结束", "fact_ids": []},
        ],
        "visual_plan": [{"kind": "detail", "card": card_record("garment-punch-v1")}] * 3,
    }
    specs = preview_specs(p, candidate)
    assert all(s["card"] is None and "清晰度" in s["basis"] for s in specs)
    candidate["visual_plan"][1] = {"kind": "action", "card": None}
    with pytest.raises(ValueError, match="说明|动作"):
        preview_specs(p, candidate)
