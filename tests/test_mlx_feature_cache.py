import pytest


class Tensor:
    def __init__(self, size):
        self.nbytes = size


def features(size=10):
    return Tensor(size), [Tensor(size), Tensor(size), Tensor(size)]


def test_cache_keeps_main_and_all_deepstack_outputs():
    from scripts.mlx_feature_cache import CompleteVisionCache

    cache = CompleteVisionCache("model+processor-sha", max_bytes=80, deepstack_layers=3)
    output = features()
    assert cache.get_or_compute("pixel-grid-key", lambda: output) is output
    assert cache.get_or_compute("pixel-grid-key", lambda: pytest.fail("re-encoded")) is output
    assert cache.hits == 1 and cache.encodes == 1 and cache.bytes == 40


def test_eviction_is_bounded_and_uses_lru():
    from scripts.mlx_feature_cache import CompleteVisionCache

    cache = CompleteVisionCache("model+processor-sha", max_bytes=80, deepstack_layers=3)
    cache.get_or_compute("a", features)
    cache.get_or_compute("b", features)
    cache.get_or_compute("a", features)
    cache.get_or_compute("c", features)
    cache.get_or_compute("b", features)
    assert cache.encodes == 4 and cache.hits == 1 and cache.bytes == 80
    cache.clear()
    assert cache.bytes == 0
    cache.get_or_compute("a", features)
    assert cache.encodes == 5


def test_oversized_output_returns_complete_without_caching():
    from scripts.mlx_feature_cache import CompleteVisionCache

    cache = CompleteVisionCache("model+processor-sha", max_bytes=20, deepstack_layers=3)
    a = cache.get_or_compute("a", features)
    b = cache.get_or_compute("a", features)
    assert len(a[1]) == len(b[1]) == 3
    assert cache.encodes == 2 and cache.hits == 0 and cache.bytes == 0


@pytest.mark.parametrize(
    "output", [(Tensor(10), None), (Tensor(10), []), (Tensor(10), [Tensor(10)])]
)
def test_missing_deepstack_is_rejected(output):
    from scripts.mlx_feature_cache import CompleteVisionCache

    cache = CompleteVisionCache("model+processor-sha", max_bytes=80, deepstack_layers=3)
    with pytest.raises(ValueError, match="DeepStack"):
        cache.get_or_compute("a", lambda: output)
    assert cache.bytes == cache.hits == 0


def test_model_and_grid_pixel_keys_are_separate():
    from scripts.mlx_feature_cache import CompleteVisionCache

    a = CompleteVisionCache("model-a+processor-a", max_bytes=80, deepstack_layers=3)
    b = CompleteVisionCache("model-b+processor-b", max_bytes=80, deepstack_layers=3)
    assert a.get_or_compute("pixels-grid-a", features) is not b.get_or_compute(
        "pixels-grid-a", features
    )
    assert a.get_or_compute("pixels-grid-a", features) is not a.get_or_compute(
        "pixels-grid-b", features
    )
    assert a.encodes == 2 and b.encodes == 1


def test_physical_array_buffers_control_eviction_not_view_nbytes():
    from scripts.mlx_feature_cache import CompleteVisionCache

    cache = CompleteVisionCache(
        "model+processor-sha", max_bytes=80, deepstack_layers=3, measure_bytes=lambda _: 120
    )
    cache.get_or_compute("a", features)
    cache.get_or_compute("a", features)
    assert cache.encodes == 2 and cache.bytes == 0
