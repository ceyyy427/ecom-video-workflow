"""Real small videos catch double rotation, changed originals and partial upload leaks."""

import json
import subprocess

import pytest

from ecom_video.media import digest, probe


def rotated_clip(tmp_path):
    source = tmp_path / "source.mp4"
    rotated = tmp_path / "phone.MP4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=30:duration=1",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            str(source),
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-display_rotation",
            "90",
            "-i",
            str(source),
            "-c",
            "copy",
            str(rotated),
        ],
        check=True,
    )
    return rotated


def test_intake_bakes_rotation_once_and_preserves_original(tmp_path):
    from ecom_video.media_intake import intake_video

    original = rotated_clip(tmp_path)
    old = digest(original)
    target = tmp_path / "work.mp4"
    meta = intake_video(original, target)
    assert digest(original) == old
    assert (meta["width"], meta["height"]) == (180, 320)
    stream = probe(target)["streams"][0]
    assert not any(s.get("rotation", 0) for s in stream.get("side_data_list", []))
    assert meta["intake"]["original_sha256"] == old
    assert meta["intake"]["transcoded"] is True
    assert abs(meta["duration"] - 1) < 0.034


def test_invalid_video_leaves_no_working_file(tmp_path):
    from ecom_video.media_intake import intake_video

    source = tmp_path / "invalid.mp4"
    source.write_bytes(b"not a movie")
    target = tmp_path / "work.mp4"
    with pytest.raises(ValueError):
        intake_video(source, target)
    assert not target.exists()
    assert source.read_bytes() == b"not a movie"


@pytest.mark.parametrize("rotation", [0, 90, 270])
def test_anamorphic_video_preserves_display_ratio(tmp_path, rotation):
    from ecom_video.media_intake import intake_video

    source = tmp_path / "anamorphic.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=720x576:rate=10:duration=0.5",
            "-vf",
            "setsar=64/45",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            str(source),
        ],
        check=True,
    )
    if rotation:
        rotated = tmp_path / "rotated.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-display_rotation",
                str(rotation),
                "-i",
                str(source),
                "-c",
                "copy",
                str(rotated),
            ],
            check=True,
        )
        source = rotated
    output = tmp_path / "square.mp4"
    m = intake_video(source, output)
    ratio = 9 / 16 if rotation else 16 / 9
    assert abs(m["width"] / m["height"] - ratio) < 0.01
    assert probe(output)["streams"][0]["sample_aspect_ratio"] == "1:1"


def test_probeable_video_with_corrupt_middle_packet_is_rejected(tmp_path):
    from ecom_video.media_intake import intake_video

    rotated_clip(tmp_path)
    source = tmp_path / "source.mp4"
    packets = json.loads(
        subprocess.check_output(
            ["ffprobe", "-v", "quiet", "-show_packets", "-of", "json", str(source)]
        )
    )["packets"]
    payload = bytearray(source.read_bytes())
    position = int(packets[1]["pos"])
    payload[position : position + 16] = b"\xff" * 16
    source.write_bytes(payload)
    assert probe(source)["streams"][0]["codec_name"] == "h264"
    target = tmp_path / "work.mp4"
    with pytest.raises(ValueError):
        intake_video(source, target)
    assert not target.exists() and source.read_bytes() == payload


def test_extreme_sar_cannot_exceed_full_hd_bounds(tmp_path):
    from ecom_video.media_intake import intake_video

    source = tmp_path / "narrow.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=16x16:rate=1:duration=1",
            "-vf",
            "setsar=1/1000:max=1000",
            "-c:v",
            "png",
            "-threads",
            "1",
            "-pix_fmt",
            "rgb24",
            str(source),
        ],
        check=True,
    )
    assert probe(source)["streams"][0]["sample_aspect_ratio"] == "1:1000"
    target = tmp_path / "work.mp4"
    with pytest.raises(ValueError, match="比例|尺寸"):
        intake_video(source, target)
    assert not target.exists()


def test_customer_video_envelope_accepts_larger_sources_but_legacy_upload_does_not(tmp_path):
    from test_customer import client, project

    c = client(tmp_path / "state")
    p = project(c)
    source = rotated_clip(tmp_path)
    # Exercise the ASGI envelope without allocating a 100MiB synthetic fixture.
    header = {"Content-Length": str(102 * 1024**2)}
    r = c.post(
        "/api/customer-projects/" + p["id"] + "/assets",
        headers=header,
        data={"revision": p["revision"], "role": "product"},
        files={"file": ("phone.MP4", source.read_bytes(), "video/mp4")},
    )
    assert r.status_code == 201, r.text
    legacy = c.post("/api/jobs", json={"title": "旧任务", "script": "外观", "seconds": 2}).json()
    r = c.post(
        "/api/jobs/" + legacy["id"] + "/assets",
        headers=header,
        data={"kind": "video"},
        files={"file": ("phone.mp4", b"bad", "video/mp4")},
    )
    assert r.status_code == 413


def test_upload_retains_original_and_confines_download_to_own_project(tmp_path):
    from test_customer import client, project

    c = client(tmp_path / "state")
    p = project(c)
    source = rotated_clip(tmp_path)
    data = source.read_bytes()
    url = "/api/customer-projects/" + p["id"]
    r = c.post(
        url + "/assets",
        data={"revision": p["revision"], "role": "product"},
        files={"file": ("phone.MP4", data, "video/mp4")},
    )
    assert r.status_code == 201, r.text
    new = r.json()
    a = new["media"][0]
    assert (a["metadata"]["width"], a["metadata"]["height"]) == (180, 320)
    original = c.get(url + "/assets/" + a["id"] + "/original")
    assert original.status_code == 200
    assert original.content == data
    other = project(c)
    assert (
        c.get(
            "/api/customer-projects/" + other["id"] + "/assets/" + a["id"] + "/original"
        ).status_code
        == 404
    )
    before = sorted(str(f) for f in (tmp_path / "state" / "customers").rglob("*") if f.is_file())
    stale = c.post(
        url + "/assets",
        data={"revision": p["revision"], "role": "product"},
        files={"file": ("phone.MP4", data, "video/mp4")},
    )
    assert stale.status_code == 409
    after = sorted(str(f) for f in (tmp_path / "state" / "customers").rglob("*") if f.is_file())
    assert before == after


def test_backup_restores_registered_original_after_removing_library_entry(tmp_path):
    from test_customer import approve, client, prepare, project

    from ecom_video.maintenance import backup, restore

    root = tmp_path / "state"
    c = client(root)
    p = project(c)
    source = rotated_clip(tmp_path)
    data = source.read_bytes()
    url = "/api/customer-projects/" + p["id"]
    p = c.post(
        url + "/assets",
        data={"revision": p["revision"], "role": "product"},
        files={"file": ("phone.MP4", data, "video/mp4")},
    ).json()
    p = prepare(c, approve(c, p))
    a = p["media"][0]
    original_relative = a["metadata"]["intake"]["original_path"]
    assert (
        c.request(
            "DELETE", url + "/assets/" + a["id"], json={"revision": p["revision"]}
        ).status_code
        == 200
    )
    bundle = tmp_path / "backup"
    backup(root, bundle)
    destination = tmp_path / "restored"
    restore(bundle, destination)
    assert (destination / original_relative).read_bytes() == data


def test_removing_unused_upload_does_not_leave_unregistered_original(tmp_path):
    from test_customer import client, project

    c = client(tmp_path / "state")
    p = project(c)
    source = rotated_clip(tmp_path)
    url = "/api/customer-projects/" + p["id"]
    p = c.post(
        url + "/assets",
        data={"revision": p["revision"], "role": "product"},
        files={"file": ("phone.mp4", source.read_bytes(), "video/mp4")},
    ).json()
    a = p["media"][0]
    original = tmp_path / "state" / a["metadata"]["intake"]["original_path"]
    assert original.exists()
    assert (
        c.request(
            "DELETE", url + "/assets/" + a["id"], json={"revision": p["revision"]}
        ).status_code
        == 200
    )
    assert not original.exists()
