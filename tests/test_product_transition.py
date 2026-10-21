from pathlib import Path

from ecom_video import product_inspection as inspect


def samples():
    return [
        {
            "time": 3.2,
            "frame": "a.jpg",
            "match": "same",
            "target_count": "one",
            "lid": "unclear",
            "handling_lid": True,
        },
        {
            "time": 4.0,
            "frame": "b.jpg",
            "match": "same",
            "target_count": "one",
            "lid": "detached",
            "handling_lid": True,
        },
    ]


def test_temporal_cap_change_requires_visible_same_unique_product(monkeypatch):
    result = {
        "same_single_product": True,
        "cap_moves_away_from_mouth": True,
        "cap_moves_onto_mouth": False,
        "hand_manipulates_cap": True,
        "visible_before_and_after": True,
        "uncertainty": "none",
    }
    monkeypatch.setattr(inspect, "generate", lambda *a, **k: result)
    events = inspect.temporal_lid_events(samples(), Path("."), {}, lambda: None)
    assert len(events) == 1 and events[0]["kind"] == "open_lid"
    assert (events[0]["start"], events[0]["end"], events[0]["anchor"]) == (3.2, 4.0, 3.6)
    for key, value in [
        ("same_single_product", False),
        ("visible_before_and_after", False),
        ("hand_manipulates_cap", False),
        ("uncertainty", "occlusion"),
        ("cap_moves_onto_mouth", True),
    ]:
        old = result[key]
        result[key] = value
        assert inspect.temporal_lid_events(samples(), Path("."), {}, lambda: None) == []
        result[key] = old


def test_temporal_does_not_bridge_unknown_identity_count_or_time(monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("ineligible pair must not query model")

    monkeypatch.setattr(inspect, "generate", forbidden)
    for key, value in [("match", "uncertain"), ("target_count", "multiple"), ("time", 7.0)]:
        rows = samples()
        rows[1][key] = value
        assert inspect.temporal_lid_events(rows, Path("."), {}, lambda: None) == []
    rows = samples()
    rows[0]["lid"] = "detached"
    assert inspect.temporal_lid_events(rows, Path("."), {}, lambda: None) == []


def test_known_state_transition_still_needs_visible_displacement(monkeypatch):
    rows = samples()
    rows[0]["lid"] = "attached"
    calls = []

    def unchanged(*args, **kwargs):
        calls.append(args)
        return {
            "same_single_product": True,
            "cap_moves_away_from_mouth": False,
            "cap_moves_onto_mouth": False,
            "hand_manipulates_cap": True,
            "visible_before_and_after": True,
            "uncertainty": "none",
        }

    monkeypatch.setattr(inspect, "generate", unchanged)
    assert inspect.temporal_lid_events(rows, Path("."), {}, lambda: None) == []
    assert len(calls) == 1
