import copy

from test_customer import approve, client, picture, plan, prepare, project


def test_timeline_readonly_scoped_and_empty(tmp_path):
    c = client(tmp_path)
    p = project(c)
    base = "/api/customer-projects/" + p["id"] + "/timeline"
    r = c.get(base)
    assert r.status_code == 200
    assert r.json()["shots"] == []
    p = plan(c, prepare(c, approve(c, picture(c, p))))
    before = copy.deepcopy(c.app.state.store.get(p["job"]["id"]))
    result = c.get(base).json()
    assert result["duration"] == round(sum(s["duration"] for s in before["storyboard"]["shots"]), 6)
    assert result["captions"] == []  # no invented word timing before render
    assert result["caption_status"] == "not_rendered"
    assert c.app.state.store.get(p["job"]["id"]) == before
    other = project(c)
    assert (
        c.get(
            "/api/customer-projects/" + other["id"] + "/timeline", params={"job_id": before["id"]}
        ).status_code
        == 404
    )


def test_subtitle_adapter_preserves_numbers_utf16_pause_and_rejects_invalid():
    from ecom_video.editor_timeline import parse_captions

    text = "1\r\n00:00:00.200 --> 00:00:01.500\r\nECP33.21 95%\r\n\r\n2\r\n00:00:02,100 --> 00:00:03,000\r\n下摆收紧\r\n"
    rows = parse_captions(text.encode("utf-16"), 4)
    assert rows == [
        {"start": 0.2, "end": 1.5, "text": "ECP33.21 95%"},
        {"start": 2.1, "end": 3.0, "text": "下摆收紧"},
    ]
    import pytest

    with pytest.raises(ValueError):
        parse_captions(b"1\n00:00:02,000 --> 00:00:01,000\nwrong", 4)
    with pytest.raises(ValueError):
        parse_captions(b"1\n00:99:02,000 --> 01:40:01,000\nwrong", 4)


def test_timeline_does_not_display_changed_or_missing_subtitle_artifact(tmp_path):
    import hashlib
    from types import SimpleNamespace

    from ecom_video.editor_timeline import timeline

    content = b"1\n00:00:00,200 --> 00:00:01,500\nproduct\n"
    path = tmp_path / "captions.srt"
    path.write_bytes(content)
    job = {
        "id": "j",
        "storyboard": {"shots": [{"shot_id": "s", "duration": 2}]},
        "artifacts": [
            {
                "kind": "subtitles",
                "path": "captions.srt",
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ],
    }
    service = SimpleNamespace(get=lambda _: {"job": job})
    assert timeline(service, tmp_path, "p")["caption_status"] == "rendered"
    path.write_bytes(content.replace(b"product", b"changed"))
    result = timeline(service, tmp_path, "p")
    assert result["caption_status"] == "unavailable" and result["captions"] == []
    path.unlink()
    assert timeline(service, tmp_path, "p")["caption_status"] == "unavailable"
