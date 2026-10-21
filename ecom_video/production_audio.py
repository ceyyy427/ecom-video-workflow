"""Frame-addressed cues. Optional locally licensed recordings are never bundled in source."""

from pathlib import Path

import numpy as np

from .media import digest, run_checked

LIBRARY = Path(__file__).resolve().parents[1] / "var/media/p6"


def make_cues(scenes, style, total, directory, check):
    rate = 48000
    track = np.zeros(round(total * rate), dtype=np.float32)
    cues = []
    for scene in scenes:
        treatment = scene["treatment"]
        if treatment == "auto":
            treatment = (
                "hero"
                if scene["index"] == 1
                else "end"
                if scene["index"] == len(scenes)
                else ["macro", "split", "context"][(scene["index"] - 2) % 3]
            )
        if style == "cinema" and treatment == "hero" and scene["frames"] >= 150:
            at, name = scene["start"] + 115 / 30, "whoosh"
        elif style == "social" and treatment in ("hero", "context"):
            at, name = scene["start"] + 24 / 30, "paper"
        elif style == "lab" and treatment == "macro":
            at, name = (
                scene["start"]
                + (0.06 + (860 / 1080) * 0.6 + 0.13) * max(scene["frames"], 138) / 30,
                "focus",
            )
        elif scene["transition"] == "wipe" and scene["index"] > 1:
            at, name = scene["start"] + 6 / 30, "whoosh"
        else:
            continue
        source = LIBRARY / (name + ".mp3")
        if source.exists():
            raw = directory / (name + ".f32")
            if not raw.exists():
                run_checked(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-y",
                        "-i",
                        str(source),
                        "-t",
                        "1.2",
                        "-ac",
                        "1",
                        "-ar",
                        str(rate),
                        "-f",
                        "f32le",
                        str(raw),
                    ],
                    check,
                )
            sound = np.fromfile(raw, dtype="<f4").copy()
            origin = {
                "source_sha256": digest(source),
                "source_kind": "local_Mixkit_recording",
                "license": "Mixkit Sound Effects Free License; end-product use only",
            }
        else:
            # A deterministic broadband air swell is the distributable fallback.
            t = np.arange(round(0.35 * rate)) / rate
            rng = np.random.default_rng(14)
            sound = (
                np.convolve(rng.normal(size=len(t)), np.ones(16) / 16, mode="same")
                * np.sin(np.pi * t / 0.35) ** 2
            )
            origin = {"source_kind": "project_original_air_swell"}
        sound /= max(float(np.abs(sound).max()), 0.001)
        sound *= 0.055 if style == "cinema" else 0.035
        edge = min(len(sound) // 2, round(0.015 * rate))
        sound[:edge] *= np.linspace(0, 1, edge)
        sound[-edge:] *= np.linspace(1, 0, edge)
        peak = int(np.argmax(np.abs(sound)))
        offset = round(at * rate) - peak
        trim = max(0, -offset)
        offset = max(0, offset)
        length = min(len(sound) - trim, len(track) - offset)
        if length <= 0:
            continue
        track[offset : offset + length] += sound[trim : trim + length]
        cues.append(
            {
                "shot_id": scene["shot_id"],
                "kind": name,
                "at": at,
                "frame": round(at * 30),
                "source_peak_seconds": peak / rate,
                "placed_start": offset / rate,
                "duration": length / rate,
                **origin,
            }
        )
    return track, cues
