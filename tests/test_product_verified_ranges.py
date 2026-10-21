"""Automatic footage never crosses unverified identity gaps or borrows their events."""

import copy

import pytest

from ecom_video.clip_matching import allocate, candidates
from ecom_video.product_motion import VERSION, action_ranges, eligible_identity, verified_ranges


def sample(time, match="same", count="one"):
    return {"time": time, "match": match, "target_count": count}


def job_for(samples, events=(), *, identity="different", source_in=0, strict=True):
    return {
        "matching_constraints": {"strict_product": strict, "reference_sha256": "reference"},
        "assets": [
            {
                "id": "video",
                "sha256": "source",
                "kind": "video",
                "metadata": {
                    "source_in": source_in,
                    "content_analysis": {
                        "analysis_id": "analysis",
                        "source_sha256": "source",
                        "segments": [
                            {
                                "id": "clip-00",
                                "start": 0,
                                "end": 10,
                                "quality": {"blank": False},
                                "observation": {"usable": True, "description": "瓶身"},
                                "motion_check": {
                                    "version": VERSION,
                                    "reference_sha256": "reference",
                                    "identity": identity,
                                    "samples": samples,
                                    "events": list(events),
                                },
                            }
                        ],
                    },
                },
            }
        ],
    }


@pytest.mark.parametrize(
    "match,count",
    [
        ("uncertain", "one"),
        ("different", "one"),
        ("same", "multiple"),
        ("same", "none"),
        ("same", "uncertain"),
        ("same", None),
    ],
)
def test_uncertain_different_and_nonunique_subjects_split_confirmed_ranges(match, count):
    samples = [sample(0.05), sample(0.8), sample(1.55, match, count), sample(2.3), sample(3.05)]
    assert verified_ranges(samples) == [{"start": 0.05, "end": 0.8}, {"start": 2.3, "end": 3.05}]


def test_single_samples_and_large_time_gaps_cannot_supply_continuous_footage():
    assert verified_ranges([sample(0.05)]) == []
    assert verified_ranges([sample(0.05), sample(2), sample(2.75)]) == [{"start": 2, "end": 2.75}]
    assert verified_ranges([sample(0), sample(1.5), sample(3.0001)]) == [{"start": 0, "end": 1.5}]


def test_different_tail_does_not_erase_verified_prefix_or_change_overall_identity():
    samples = [sample(0.05 + 0.75 * i) for i in range(11)] + [sample(8.75, "different")]
    job = job_for(samples)
    original = copy.deepcopy(job)
    pool = candidates(job)
    assert len(pool) == 1
    chosen = pool[0]
    assert chosen["start"] >= 0.05 and chosen["end"] <= 7.55
    assert chosen["verified_range"] == {"start": 0.05, "end": 7.55}
    assert chosen["motion_check"]["identity"] == "different"
    assert eligible_identity(chosen, job["matching_constraints"])
    assert job == original
    assert not eligible_identity({**chosen, "end": 8.75}, job["matching_constraints"])


def test_candidates_never_cross_unknown_gap_or_keep_an_event_crossing_it():
    samples = [
        sample(0),
        sample(0.75),
        sample(1.5),
        sample(2.25, "uncertain"),
        sample(3),
        sample(3.75),
        sample(4.5),
    ]
    events = [
        {"kind": "open_lid", "start": 0.75, "end": 1.5, "anchor": 1.125},
        {"kind": "pour", "start": 1.5, "end": 3.75, "anchor": 1.5},
        {"kind": "close_lid", "start": 3.75, "end": 4.5, "anchor": 4.125},
    ]
    job = job_for(samples, events)
    pool = candidates(job)
    assert [(c["start"], c["end"]) for c in pool] == [(0, 1.5), (3, 4.5)]
    assert [[e["kind"] for e in c["motion_check"]["events"]] for c in pool] == [
        ["open_lid"],
        ["close_lid"],
    ]
    assert not eligible_identity(
        {**pool[0], "end": 4.5, "verified": True}, job["matching_constraints"]
    )
    assert all(not action_ranges(c, 1, [{"kind": "pour", "start": 0.1, "end": 0.5}]) for c in pool)
    ranks = [
        {
            "line": 1,
            "choices": [{"clip_id": c["id"], "score": 3, "reason": "fixture"} for c in pool],
        }
    ]
    with pytest.raises(ValueError, match="未找到"):
        allocate(["瓶身"], [2], pool, ranks, "showcase", job["matching_constraints"])


def test_inward_frame_bounds_and_source_in_stay_inside_verified_samples():
    job = job_for([sample(0.01 + 0.75 * i) for i in range(7)], source_in=1.01)
    pool = candidates(job)
    assert len(pool) == 1
    assert pool[0]["start"] == 31 / 30
    assert pool[0]["end"] == 4.5
    assert eligible_identity(pool[0], job["matching_constraints"])


def test_v2_results_cannot_be_reinterpreted_as_verified_v3_ranges():
    job = job_for([sample(0), sample(0.75), sample(1.5)], identity="same")
    job["assets"][0]["metadata"]["content_analysis"]["segments"][0]["motion_check"]["version"] = (
        "reference-motion-v2"
    )
    assert candidates(job) == []


def test_nonstrict_legacy_candidates_keep_full_source_ranges():
    job = job_for([sample(0, "different")], strict=False)
    pool = candidates(job)
    assert [(c["start"], c["end"]) for c in pool] == [(0, 10)]


def test_reference_only_excludes_calibration_image_but_retains_other_images():
    job = job_for([sample(t) for t in range(10)], identity="same")
    for key in ("reference", "photo"):
        asset = copy.deepcopy(job["assets"][0])
        asset.update(id=key, kind="image", sha256=key)
        asset["metadata"]["content_analysis"]["source_sha256"] = key
        job["assets"].append(asset)
    assert {c["asset_id"] for c in candidates(job)} == {"video", "reference", "photo"}
    job["matching_constraints"]["reference_only"] = True
    assert {c["asset_id"] for c in candidates(job)} == {"video", "photo"}
    job["matching_constraints"]["strict_product"] = False
    assert {c["asset_id"] for c in candidates(job)} == {"video", "photo"}
