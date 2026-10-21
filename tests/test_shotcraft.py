import copy

import pytest
from pydantic import ValidationError

from ecom_video.creative import Brief, recommend
from ecom_video.storyboard import Shot


def test_new_plan_uses_script_intent_and_preserves_original_text_and_media(tmp_path):
    from test_customer import approve, client, picture, prepare, project

    c = client(tmp_path)
    p = prepare(c, approve(c, picture(c, project(c))))
    job = p["job"]
    r = c.post(
        f"/api/customer-projects/{p['id']}/plan",
        json={
            "revision": p["revision"],
            "job_id": job["id"],
            "board_revision": job["storyboard_revision"],
            "style_id": "cinema",
            "fingerprint": p["recommendations"]["fingerprint"],
        },
    )
    assert r.status_code == 200, r.text
    planned = r.json()["job"]
    assert planned["script"] == job["script"]
    assert all(s.get("shot_recipe") for s in planned["storyboard"]["shots"])
    assert all(
        s["asset_id"] in {a["id"] for a in job["assets"]} for s in planned["storyboard"]["shots"]
    )


def test_motion_contract_rejects_arbitrary_code_and_retains_legacy_default():
    assert Shot().model_dump().get("shot_recipe") is None
    for recipe in ["marker-underline-title", "none"]:
        assert Shot(shot_recipe=recipe).shot_recipe == recipe
    with pytest.raises(ValidationError):
        Shot(shot_recipe="eval(fetch('https://example.com'))")
    assert Shot(transition="push-stack").transition == "push-stack"


def test_intent_planning_has_energy_limits_and_never_invents_claims():
    from ecom_video.shotcraft import choreography

    lines = [
        "耳机细节先看这里。",
        "折叠耳罩，再放入包里。",
        "接口与材质清楚可见。",
        "一起看看外观。",
    ]
    energetic = choreography(lines, "kinetic", [3] * 4)
    calm = choreography(lines, "quiet", [3] * 4)
    assert energetic[0]["shot_recipe"] == "crash-zoom-punch"
    assert calm[0]["shot_recipe"] == "marker-underline-title"
    assert energetic[1]["shot_recipe"] == "product-card-progressive-assemble"
    assert energetic[2]["shot_recipe"] == "scanline-annotate-focus"
    assert energetic[-1]["shot_recipe"] == "none"
    assert sum(s["transition"] == "line-carry" for s in calm) <= 1
    short = choreography(lines, "kinetic", [1] * 4)
    assert all(s["shot_recipe"] != "crash-zoom-punch" for s in short)
    assert choreography(lines, "kinetic", [3] * 4) == energetic


def test_recommendations_explain_three_supported_motion_palettes_without_reranking():
    job = {
        "title": "耳机",
        "script": "折叠耳罩，放进包里。",
        "assets": [{"kind": "video", "sha256": "x"}],
    }
    before = copy.deepcopy(job)
    r = recommend(job, Brief(category="数码", audience="学生", tone="活泼节奏"))
    assert len(r["options"]) == 3
    assert len({tuple(s["motion"]["recipes"]) for s in r["options"]}) > 1
    assert all(s["motion"]["description"] for s in r["options"])
    assert job == before


def test_prompt_provenance_is_local_data_with_original_text_and_version():
    from ecom_video.shotcraft import recipe_record

    record = recipe_record("marker-underline-title", "瓶身颜色清楚可见。", "瓶身颜色", "editorial")
    assert record["source"]["commit"] == "43bd349a136651865ecfa6ea1cf012f6e957d304"
    assert record["source"]["license"] == "Apache-2.0"
    assert record["approved_text"] == "瓶身颜色清楚可见。"
    assert record["headline"] == "瓶身颜色"
    assert record["prompt"] and record["reason"]
    with pytest.raises(ValueError):
        recipe_record("marker-underline-title", "瓶身颜色清楚可见。", "美白功效", "editorial")


def test_single_recipe_revision_keeps_parent_and_all_other_edit_decisions(tmp_path):
    from test_customer import approve, client, lock_and_revision, picture, plan, prepare, project

    c = client(tmp_path)
    p = plan(c, prepare(c, approve(c, picture(c, project(c)))))
    original = copy.deepcopy(p["job"])
    payload = lock_and_revision(c, p)
    payload["changes"] = {"shot_recipe": "none"}
    base = f"/api/customer-projects/{p['id']}"
    result = c.post(base + "/revise-shot", json=payload)
    assert result.status_code == 201, result.text
    child = result.json()["job"]
    assert child["parent_id"] == original["id"]
    assert child["script"] == original["script"]
    assert c.get(f"/api/jobs/{original['id']}").json()["storyboard"] == original["storyboard"]
    for old, new in zip(original["storyboard"]["shots"], child["storyboard"]["shots"], strict=True):
        # The version copies assets to a new job; compare content identity independently below.
        assert {k: v for k, v in new.items() if k not in ("asset_id", "shot_recipe")} == {
            k: v for k, v in old.items() if k not in ("asset_id", "shot_recipe")
        }
        assert new["shot_recipe"] == (
            "none" if old["shot_id"] == payload["shot_id"] else old["shot_recipe"]
        )
        assert next(a["sha256"] for a in child["assets"] if a["id"] == new["asset_id"]) == next(
            a["sha256"] for a in original["assets"] if a["id"] == old["asset_id"]
        )


def test_new_recipe_subtitle_pixels_keep_ink_contrast_on_paper():
    import base64
    import io

    from PIL import Image

    from ecom_video.subtitle_layout import prepare_captions

    captions = prepare_captions(
        {
            "shotRecipe": "none",
            "text": "颜色清楚可见",
            "words": [],
            "voiceStart": 0,
            "voiceEnd": 2,
            "style": "quiet",
            "treatment": "footage",
            "brand": {"ink": "#123456", "paper": "#ffffff", "subtitle_size": 60},
        }
    )
    im = Image.open(io.BytesIO(base64.b64decode(captions[0]["image"].split(",", 1)[1]))).convert(
        "RGBA"
    )
    colors = [pixel[:3] for pixel in im.get_flattened_data() if pixel[3] == 255]
    assert colors and set(colors) == {(18, 52, 86)}


@pytest.mark.parametrize("transition", ["transition", "exitTransition"])
def test_legacy_transition_only_recipe_route_uses_readable_subtitles(transition):
    import base64
    import io

    from PIL import Image

    from ecom_video.subtitle_layout import prepare_captions

    captions = prepare_captions(
        {
            transition: "push-stack",
            "text": "看清商品",
            "words": [],
            "voiceStart": 0,
            "voiceEnd": 1,
            "style": "quiet",
            "treatment": "footage",
            "brand": {"ink": "#123456", "paper": "#ffffff", "subtitle_size": 60},
        }
    )
    im = Image.open(io.BytesIO(base64.b64decode(captions[0]["image"].split(",", 1)[1]))).convert(
        "RGBA"
    )
    assert {(r, g, b) for r, g, b, a in im.get_flattened_data() if a == 255} == {(18, 52, 86)}
