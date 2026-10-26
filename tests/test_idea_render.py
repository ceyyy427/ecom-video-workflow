import pytest


def test_renderer_rejects_unknown_code_geometry_and_uses_literal_facts():
    from ecom_video.content_plan import ContentBrief, build_plan
    from ecom_video.idea_renderer import visual_spec

    p = build_plan(
        ContentBrief(idea="解释桥梁如何承重", facts=[{"text": "观察桥墩", "source": "资料一"}]), []
    )
    a = visual_spec(p, p["options"][0], p["options"][0]["scenes"][1])
    assert a["labels"] == ["观察桥墩"]
    assert a["data"] == [] and a["schematic"] is True
    b = dict(p["options"][0], diagram="arbitrary-script")
    with pytest.raises(ValueError):
        visual_spec(p, b, b["scenes"][0])


def test_source_changed_or_incomplete_action_cannot_be_hidden_by_preview(tmp_path):
    from ecom_video.idea_media import check_materials
    from ecom_video.media import digest

    a = tmp_path / "a.png"
    a.write_bytes(b"original")
    material = {
        "id": "a",
        "path": "a.png",
        "sha256": digest(a),
        "kind": "image",
        "source_in": 0,
        "metadata": {},
    }
    check_materials(tmp_path, [material])
    a.write_bytes(b"changed")
    with pytest.raises(ValueError, match="变化"):
        check_materials(tmp_path, [material])


def test_new_presentations_keep_old_board_defaults_and_validate_code_schema():
    from ecom_video.idea_renderer import CodeVisual
    from ecom_video.storyboard import Shot

    assert Shot().presentation is None
    assert Shot(presentation="design").presentation == "design"
    with pytest.raises(ValueError):
        CodeVisual.model_validate({"kind": "evil", "labels": ["ok"]})


def test_empty_worker_has_no_approval_side_effects(tmp_path):
    from ecom_video.worker import Worker

    worker = Worker(tmp_path)
    assert worker.run_once() is False
    with worker.store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 0
