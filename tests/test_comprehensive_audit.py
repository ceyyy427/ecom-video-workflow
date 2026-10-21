"""Catch false audit clearance, lost timestamps and unescaped report content."""

import copy
import json
from pathlib import Path

import pytest
from test_customer import approve, client, picture, plan, prepare, project


def test_native_ocr_protocol_is_not_corrupted_by_compiler_diagnostics(tmp_path, monkeypatch):
    from ecom_video import audit_media

    monkeypatch.setattr(audit_media.sys, "platform", "darwin")
    monkeypatch.setattr(audit_media.shutil, "which", lambda _: "/usr/bin/swift")

    def process(args, *a, **kwargs):
        Path(args[2]).write_text(json.dumps({"frames": [{"texts": [{"text": "100%有效"}]}]}))
        return "swift compiler diagnostic on stderr"

    monkeypatch.setattr(audit_media, "run_checked", process)
    r = audit_media.scan_ocr([tmp_path / "frame.jpg"])
    assert r["frames"][0]["texts"][0]["text"] == "100%有效"


def test_report_locates_ocr_and_actual_audio_risks_without_approving():
    from ecom_video.comprehensive_audit import build_report

    snap = {"script": "展示黑色耳机", "assets": [], "seconds": 3}
    before = copy.deepcopy(snap)
    media = {
        "ocr": {
            "status": "sampled",
            "frames": [{"time": 1.5, "texts": [{"text": "100%有效", "confidence": 0.9}]}],
        },
        "asr": {"status": "checked", "words": [{"text": "绝对安全", "start": 0.4, "end": 1.2}]},
    }
    report = build_report("j1", snap, {"duration": 3}, media)
    assert report["status"] == "needs_review"
    assert report["human_review_required"]
    assert any(f["source"] == "ocr" and f["time"] == 1.5 for f in report["findings"])
    assert any(f["source"] == "asr" and f["time"] == 0.4 for f in report["findings"])
    assert any(f["rule_id"] == "spoken_script_difference" for f in report["findings"])
    sections = {s["id"]: s for s in report["sections"]}
    assert sections["rights"]["status"] == "not_checked"
    assert sections["ocr"]["status"] == "sampled"
    assert snap == before


def test_disabled_failed_and_silent_checks_cannot_be_reported_as_complete():
    from ecom_video.comprehensive_audit import build_report

    r = build_report(
        "j1",
        {"script": "外观", "assets": [], "seconds": 3},
        {},
        {
            "ocr": {"status": "error", "reason": "本机不可用"},
            "asr": {"status": "not_applicable", "reason": "无口播"},
        },
    )
    assert not r["coverage"]["ocr"] and not r["coverage"]["audio_asr"]
    assert any(f["rule_id"] == "check_unavailable" for f in r["findings"])
    assert r["status"] == "needs_review"


def test_standalone_html_escapes_uploaded_content_and_includes_unchecked_scope():
    from ecom_video.comprehensive_audit import build_report, html_report

    r = build_report(
        "j1", {"script": "<script>alert(1)</script>", "assets": [], "seconds": 3}, {}, {}
    )
    html = html_report(r)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "未检查" in html and "rights" in html


def test_legacy_audio_timeline_uses_actual_rendered_scenes_not_nominal_seconds():
    from ecom_video.comprehensive_audit import build_report

    snap = {"script": "外观\n细节", "assets": [], "seconds": 3}
    actual = [{"start": 0, "end": 1.5}, {"start": 1.5, "end": 4}]
    r = build_report(
        "j1",
        snap,
        {},
        {"ocr": {"status": "sampled", "frames": [{"time": 2, "texts": [{"text": "绝对安全"}]}]}},
        actual_scenes=actual,
    )
    assert r["findings"][0]["line"] == 2
    assert r["scenes"][1]["start"] == 1.5


def test_risk_phrase_split_across_ocr_boxes_is_still_located_at_sample_time():
    from ecom_video.comprehensive_audit import build_report

    r = build_report(
        "j1",
        {"script": "外观", "assets": [], "seconds": 3},
        {},
        {
            "ocr": {
                "status": "sampled",
                "frames": [{"time": 1.2, "texts": [{"text": "100%"}, {"text": "有效"}]}],
            }
        },
    )
    assert any(f["source"] == "ocr" and f["time"] == 1.2 for f in r["findings"])


def test_spoken_difference_is_located_in_second_sentence_not_always_at_zero():
    from ecom_video.comprehensive_audit import build_report

    r = build_report(
        "j1",
        {"script": "黑色耳机\n弧形头梁", "assets": [], "seconds": 3},
        {},
        {
            "asr": {
                "status": "checked",
                "words": [
                    {"text": "黑色耳机", "start": 0.5, "end": 2.5},
                    {"text": "方形头梁", "start": 3.5, "end": 5.5},
                ],
            }
        },
    )
    diff = next(f for f in r["findings"] if f["rule_id"] == "spoken_script_difference")
    assert diff["line"] == 2 and diff["time"] == 3.5


def test_selected_range_cannot_inherit_action_from_elsewhere_in_source_segment():
    from test_script_readiness import asset

    from ecom_video.comprehensive_audit import build_report

    a = asset(actions=["双手向内转动耳罩"], description="黑色耳机，耳罩圆润")
    a["metadata"]["duration"] = 20
    a["metadata"]["content_analysis"]["segments"][0]["end"] = 20
    snap = {
        "script": "把两侧耳罩向内转动",
        "assets": [a],
        "seconds": 3,
        "storyboard": {
            "shots": [{"asset_id": "v1", "shot_id": "s1", "source_in": 10, "duration": 3}]
        },
    }
    r = build_report("j1", snap, {}, {})
    row = r["scenes"][0]["material"]
    assert row["status"] == "unknown" and row["code"] == "action_time_unverified"


@pytest.mark.parametrize("error", [RuntimeError("task deadline"), "agent"])
def test_media_audit_never_swallows_cancellation_or_budget_exceptions(tmp_path, monkeypatch, error):
    from ecom_video.agent_contracts import Problem
    from ecom_video.audit_media import collect

    monkeypatch.setenv("ECOM_MEDIA_AUDIT", "1")
    if error == "agent":
        error = Problem("DEADLINE_EXCEEDED")

    def stop():
        raise error

    with pytest.raises(type(error)):
        collect(tmp_path / "film.mp4", tmp_path, "外观", [{"start": 0, "end": 3}], False, stop)


def test_media_model_budget_rejection_propagates_before_native_processing(tmp_path, monkeypatch):
    from ecom_video import agent_guard, audit_media
    from ecom_video.agent_contracts import Problem

    monkeypatch.setenv("ECOM_MEDIA_AUDIT", "1")
    monkeypatch.setattr(audit_media.sys, "platform", "darwin")
    monkeypatch.setattr(audit_media.shutil, "which", lambda _: "/usr/bin/swift")
    monkeypatch.setattr(audit_media, "run_checked", lambda *a, **kw: None)

    def refuse():
        raise Problem("BUDGET_EXCEEDED")

    monkeypatch.setattr(agent_guard, "reserve_call", refuse)
    with pytest.raises(Problem):
        audit_media.collect(
            tmp_path / "film.mp4", tmp_path, "外观", [{"start": 0, "end": 3}], False
        )


def test_worker_registers_frozen_reports_and_keeps_final_human_review(tmp_path, monkeypatch):
    from ecom_video.worker import Worker

    monkeypatch.delenv("ECOM_MEDIA_AUDIT", raising=False)
    c = client(tmp_path)
    p = plan(c, prepare(c, approve(c, picture(c, project(c)))))
    jid = p["job"]["id"]
    assert (
        c.post(
            f"/api/customer-projects/{p['id']}/submit",
            json={
                "revision": p["revision"],
                "job_id": jid,
                "board_revision": p["job"]["storyboard_revision"],
            },
        ).status_code
        == 200
    )
    Worker(tmp_path).run_once()
    job = c.get("/api/jobs/" + jid).json()
    assert job["status"] == "needs_review", job["error"]
    assert not job["reviews"]
    assert {"audit", "audit_html"} <= {a["kind"] for a in job["artifacts"]}
    report = c.get(f"/api/jobs/{jid}/artifacts/audit").json()
    assert report["job_id"] == jid and report["schema_version"] == 2
    assert report["snapshot_sha256"] and report["output_sha256"]
    assert any(
        s["id"] == "source_integrity" and s["status"] == "checked" for s in report["sections"]
    )
    assert c.get(f"/api/jobs/{jid}/artifacts/audit_html").status_code == 200
    # Repeated download must not recompute or approve the report.
    assert json.loads(c.get(f"/api/jobs/{jid}/artifacts/audit").text) == report
