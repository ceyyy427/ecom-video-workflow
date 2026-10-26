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


def test_six_preview_backup_keeps_uploads_originals_and_rendered_versions(tmp_path):
    import io

    from PIL import Image

    from ecom_video.content_plan import ContentBrief
    from ecom_video.db import Store
    from ecom_video.idea_media import resolve, upload
    from ecom_video.idea_plans import IdeaPlans
    from ecom_video.maintenance import backup, restore
    from ecom_video.media import digest
    from ecom_video.products import encoded

    root = tmp_path / "data"
    root.mkdir()
    store = Store(root / "workflow.db")
    image = io.BytesIO()
    Image.new("RGB", (60, 80), "white").save(image, format="PNG")
    ref = upload(root, store, io.BytesIO(image.getvalue()), "test.png", "自制测试图，仅工程验证")
    brief = ContentBrief(idea="观察图形", materials=[{"origin": "upload", "id": ref["id"]}])
    svc = IdeaPlans(root, store)
    p = svc.create(brief, resolve(root, store, brief))
    out = root / "ideas/previews" / p["id"]
    out.mkdir(parents=True)
    marker = out / "poster.png"
    marker.write_bytes(image.getvalue())
    with store.transaction() as c:
        c.execute(
            "UPDATE idea_plans SET previews=? WHERE id=?",
            (
                encoded(
                    {
                        "swiss-motion": {
                            "poster": {
                                "path": marker.relative_to(root).as_posix(),
                                "sha256": digest(marker),
                            }
                        }
                    }
                ),
                p["id"],
            ),
        )
    bundle = tmp_path / "bundle"
    backup(root, bundle)
    target = tmp_path / "restored"
    restore(bundle, target)
    assert (target / ref["id"]).exists() is False
    restored = IdeaPlans(target, Store(target / "workflow.db")).get(p["id"])
    assert (target / restored["plan"]["materials"][0]["path"]).is_file()
    assert (target / marker.relative_to(root)).is_file()


def test_preview_retry_never_mixes_engine_versions(tmp_path):
    from ecom_video.content_plan import ContentBrief, build_plan
    from ecom_video.idea_renderer import render_option

    plan = build_plan(ContentBrief(idea="这个主题尚待确认"), [], engine="old-render-engine")
    with pytest.raises(ValueError, match="引擎"):
        render_option(plan, plan["options"][0], tmp_path, tmp_path / "render")
    assert not (tmp_path / "render").exists()


def test_edited_script_cannot_keep_stale_diagram_text():
    from ecom_video.idea_adoption import validate_diagram

    spec = {
        "kind": "blueprint",
        "subject": "桥墩",
        "labels": ["桥墩为红色"],
        "data": [],
        "schematic": True,
        "tone": "清楚",
    }
    with pytest.raises(ValueError, match="图示"):
        validate_diagram({"metadata": {"code_visual": spec}}, "桥墩为蓝色", {})


def test_identical_renderer_can_move_to_customer_directory_without_changing_cache_version(
    tmp_path, monkeypatch
):
    import shutil

    import ecom_video.remotion_renderer as engine

    before = engine.engine_hash()
    clone = tmp_path / "installed"
    shutil.copytree(
        engine.ENGINE, clone / "render/remotion", ignore=shutil.ignore_patterns("node_modules")
    )
    (clone / "ecom_video").mkdir(parents=True)
    for file in (engine.PROJECT / "ecom_video").glob("*.py"):
        shutil.copyfile(file, clone / "ecom_video" / file.name)
    monkeypatch.setattr(engine, "PROJECT", clone)
    monkeypatch.setattr(engine, "ENGINE", clone / "render/remotion")
    monkeypatch.setattr(engine, "__file__", str(clone / "ecom_video/remotion_renderer.py"))
    assert engine.engine_hash() == before


def test_applying_presentation_never_overwrites_safe_matcher_source_or_windows():
    from ecom_video.idea_adoption import apply_board

    option = {
        "native_style": "lab",
        "scenes": [
            {
                "id": "scene-01",
                "text": "看完整开盖",
                "material_id": "original",
                "recipe": "scanline-annotate-focus",
                "transition": "cut",
                "seconds": 6,
            }
        ],
    }
    job = {
        "script": "看完整开盖",
        "provenance": {
            "idea_plan": {"plan_id": "plan", "option_id": "blueprint", "option": option}
        },
        "assets": [
            {
                "id": "asset",
                "kind": "video",
                "metadata": {"idea_material_id": "original", "source_in": 0, "duration": 30},
            }
        ],
    }
    board = {
        "creative": {"style_id": "lab"},
        "shots": [
            {
                "asset_id": "safe",
                "source_in": 10,
                "duration": 6,
                "motion_plan": {"windows": [{"start": 0.5, "end": 1.5, "basis": "analysis"}]},
            }
        ],
    }
    apply_board(job, board, "showcase", [], preserve_media=True)
    assert board["shots"][0]["asset_id"] == "safe" and board["shots"][0]["source_in"] == 10
    assert board["shots"][0]["motion_plan"]["windows"] == [
        {"start": 0.5, "end": 1.5, "basis": "analysis"}
    ]


def test_existing_manual_complete_action_is_frozen_as_evidence_not_new_approval(tmp_path):
    import json

    from ecom_video.customer import Customers
    from ecom_video.customer_api import Settings
    from ecom_video.db import Store
    from ecom_video.idea_media import attach_existing_checks

    store = Store(tmp_path / "workflow.db")
    p = Customers(tmp_path, store).create("工程动作夹具", Settings().model_dump())
    job = store.create_job("工程旧镜头", "仅验证来源区间")
    asset = {"id": "old-asset", "name": "fixture.mp4", "sha256": "a" * 64, "kind": "video"}
    board = {
        "shots": [
            {
                "shot_id": "old-shot",
                "asset_id": "old-asset",
                "source_in": 0,
                "duration": 6,
                "source_cuts": [
                    {
                        "asset_id": "old-asset",
                        "source_in": 0,
                        "source_duration": 6,
                        "duration": 6,
                        "complete_action": {"name": "开盖", "start": 1, "end": 2},
                    }
                ],
            }
        ]
    }
    item = {"id": "library-a", "sha256": "a" * 64, "metadata": {}, "kind": "video"}
    with store.transaction() as c:
        c.execute(
            "INSERT INTO customer_jobs VALUES(?,?,?,?,?,?)",
            (job["id"], p["id"], "fixture-input", "fixture-basis", "[]", 0),
        )
        c.execute(
            "UPDATE jobs SET storyboard=?,snapshot=? WHERE id=?",
            (json.dumps(board), json.dumps({"assets": [asset]}), job["id"]),
        )
        attach_existing_checks(c, item, p["id"])
    action = item["metadata"]["complete_actions"][0]
    assert (action["start"], action["end"], action["basis"]) == (1, 2, "manual_annotation")
    assert item["metadata"]["inspection_status"] == "unknown_or_stale"
    assert item["metadata"]["verified_visible_ranges"] == []


def test_known_source_actions_get_frame_relative_windows_and_cannot_be_truncated():
    from ecom_video.idea_media import source_windows

    asset = {
        "metadata": {
            "complete_actions": [
                {"name": "开盖", "start": 10.5, "end": 11.5, "basis": "manual_annotation"}
            ],
            "verified_visible_ranges": [{"start": 10, "end": 16}],
        }
    }
    assert source_windows(asset, 10, 6) == [{"start": 0.5, "end": 1.5, "basis": "manual"}]
    with pytest.raises(ValueError, match="完整动作"):
        source_windows(asset, 11, 4)
    with pytest.raises(ValueError, match="可见"):
        source_windows(asset, 0, 6)


@pytest.mark.parametrize(
    "start,source_duration,duration,message",
    [(11, 4, 4, "完整动作"), (0, 4, 4, "可见"), (10, 6, 3, "原速")],
)
def test_multi_cut_editor_cannot_bypass_known_source_guards(
    start, source_duration, duration, message
):
    from ecom_video.delivery_plan import validate_delivery

    asset = {
        "id": "v",
        "sha256": "a" * 64,
        "kind": "video",
        "metadata": {
            "duration": 30,
            "complete_actions": [
                {"name": "开盖", "start": 10.5, "end": 11.5, "basis": "manual_annotation"}
            ],
            "verified_visible_ranges": [{"start": 10, "end": 16}],
        },
    }
    board = {
        "delivery": {"version": 1, "identity_lock": None},
        "shots": [
            {
                "asset_id": "v",
                "source_in": start,
                "duration": duration,
                "motion_plan": None,
                "source_cuts": [
                    {
                        "asset_id": "v",
                        "source_in": start,
                        "source_duration": source_duration,
                        "duration": duration,
                    }
                ],
            }
        ],
    }
    with pytest.raises(ValueError, match=message):
        validate_delivery({"assets": [asset]}, board)


def test_preview_concat_supports_quotes_and_spaces_in_customer_directory(tmp_path):
    from ecom_video.idea_renderer import join_preview_clips
    from ecom_video.media import probe, run_checked

    folder = tmp_path / "customer's video folder"
    clips = folder / "clips"
    clips.mkdir(parents=True)
    for name, color in [("one", "black"), ("two", "white")]:
        run_checked(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s=80x120:r=30:d=0.5",
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(clips / (name + ".mp4")),
            ]
        )
    result = join_preview_clips(folder, [{"key": "one"}, {"key": "two"}])
    assert abs(float(probe(result)["format"]["duration"]) - 1) < 0.06
