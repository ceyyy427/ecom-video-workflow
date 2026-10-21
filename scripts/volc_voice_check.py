#!/usr/bin/env python3
"""Local configuration check; --probe explicitly sends one fixed short TTS request."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ecom_video.media import inspect_media  # noqa: E402
from ecom_video.volc_voice import VoiceError, read_config, status, synthesize  # noqa: E402

PROBE_TEXT = "你好，这是一条配音授权测试。"


def check(probe=False, transport=None):
    result = status()
    result.update(
        network_calls=0,
        credential_source="environment" if "DOUBAO_TTS_API_KEY" in os.environ else "private_file",
        review_state="not_probed",
    )
    if not probe:
        return result
    try:
        key, speaker = read_config()
        result["network_calls"] = 1
        audio = synthesize(PROBE_TEXT, speaker, key, transport)
    except VoiceError as exc:
        return {**result, **exc.details(), "review_state": "blocked"}
    try:
        with tempfile.TemporaryDirectory(prefix="ecom-voice-check-") as directory:
            path = Path(directory) / "probe.mp3"
            path.write_bytes(audio)
            path.chmod(0o600)
            meta = inspect_media(path, "audio")
    except (OSError, ValueError, subprocess.SubprocessError):
        return {
            **result,
            "error_code": "invalid_audio",
            "review_state": "blocked",
            "message": "供应商返回的声音未通过本机音频检查；未保存或批准。",
        }
    return {
        **result,
        "live_verified": True,
        "duration": meta["duration"],
        "audio_sha256": hashlib.sha256(audio).hexdigest(),
        "review_state": "needs_listening",
        "message": "本次短句合成和音频检查成功；不代表其他音色、长稿或三条样片已通过人工听核。测试音频已清理。",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--probe", action="store_true", help="发送一次固定短句，可能按账户计费；不自动重试"
    )
    args = parser.parse_args(argv)
    result = check(args.probe)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(not result["configured"] or (args.probe and not result["live_verified"]))


if __name__ == "__main__":
    raise SystemExit(main())
