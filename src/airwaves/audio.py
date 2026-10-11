"""Shared stereo sample-rate conversion for HD Radio and DAB playback."""
import numpy as np


class Resampler:
    """Linear interpolation with an exact position carried between blocks."""

    def __init__(self, in_rate, out_rate):
        self.in_rate = in_rate
        self.out_rate = out_rate
        self.reset()

    def reset(self):
        self.last = np.zeros((1, 2), dtype=np.float32)
        self.position = 0

    def process(self, audio):
        samples = np.concatenate((self.last, audio))
        end = len(samples) - 1
        count = max(0, -(-(end * self.out_rate - self.position) // self.in_rate))
        positions = (self.position + np.arange(count) * self.in_rate) / self.out_rate
        index = positions.astype(int)
        fraction = (positions - index)[:, None]
        out = samples[index] * (1 - fraction) + samples[np.minimum(index + 1, end)] * fraction
        self.position += count * self.in_rate - end * self.out_rate
        self.last = samples[-1:]
        return out.astype(np.float32)
