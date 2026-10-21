"""Sleep/clock shifts must not make a long model call look artificially fast."""

from scripts import benchmark_material_cold as bench


def test_normal_elapsed_clocks_agree(monkeypatch):
    monkeypatch.setattr(bench.time, "monotonic", lambda: 15)
    monkeypatch.setattr(bench.time, "time", lambda: 105.02)
    timing = bench.measured(10, 100)
    assert timing["measurement_valid"]
    assert timing["seconds"] == 5 and timing["wall_seconds"] == 5.02


def test_suspend_gap_or_clock_jump_invalidates_speed_measurement(monkeypatch):
    monkeypatch.setattr(bench.time, "monotonic", lambda: 15)
    monkeypatch.setattr(bench.time, "time", lambda: 1900)
    timing = bench.measured(10, 100)
    assert not timing["measurement_valid"] and timing["clock_gap_seconds"] == 1795
