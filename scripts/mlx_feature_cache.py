"""Experimental, in-memory cache for COMPLETE Qwen3-VL vision-tower outputs.

Used by isolated acceptance tooling only; no production backend selection.
Upstream processed_image_key supplies pixel/grid identity. The owner must bind
one cache to one immutable model+processor and evaluate lazy arrays before put.
"""

from collections import OrderedDict


class CompleteVisionCache:
    def __init__(self, namespace, *, max_bytes, deepstack_layers, measure_bytes=None):
        if not namespace or not 0 <= max_bytes <= 256 * 1024**2 or deepstack_layers < 1:
            raise ValueError("无效的隔离视觉缓存配置")
        self.namespace = namespace
        self.max_bytes = max_bytes
        self.deepstack_layers = deepstack_layers
        self.measure_bytes = measure_bytes or (
            lambda output: sum(a.nbytes for a in (output[0], *output[1]))
        )
        self.entries = OrderedDict()
        self.bytes = self.hits = self.encodes = 0

    def get_or_compute(self, pixel_grid_key, encode):
        key = (self.namespace, pixel_grid_key)
        if key in self.entries:
            self.hits += 1
            self.entries.move_to_end(key)
            return self.entries[key][0]
        output = encode()
        self.encodes += 1
        if (
            not isinstance(output, tuple)
            or len(output) != 2
            or not isinstance(output[1], (tuple, list))
            or len(output[1]) != self.deepstack_layers
        ):
            raise ValueError("视觉输出缺少完整 DeepStack，未缓存或继续推理")
        size = self.measure_bytes(output)
        if size > self.max_bytes:
            return output
        while self.entries and self.bytes + size > self.max_bytes:
            _, (_, removed) = self.entries.popitem(last=False)
            self.bytes -= removed
        self.entries[key] = output, size
        self.bytes += size
        return output

    def clear(self):
        self.entries.clear()
        self.bytes = 0
