import numpy as np


def float32_to_int16(x):
    return (x * 32767).astype(np.int16)


def int16_to_float32(x):
    return x.astype(np.float32) / 32768.0


def db_to_linear(db):
    return 10.0 ** (db / 20.0)


def linear_to_db(linear):
    return 20.0 * np.log10(np.maximum(linear, 1e-9))


class RingBuffer:
    def __init__(self, capacity, channels=2, dtype=np.float32):
        self.capacity = capacity
        self.channels = channels
        self.dtype = dtype
        self.buffer = np.zeros((capacity, channels), dtype=dtype)
        self.write_ptr = 0
        self.read_ptr = 0
        self.size = 0

    def write(self, data):
        frames = data.shape[0]
        if frames == 0:
            return 0

        writable = self.capacity - self.size
        if frames > writable:
            frames = writable

        if frames == 0:
            return 0

        idx1 = self.write_ptr
        len1 = min(frames, self.capacity - idx1)
        self.buffer[idx1 : idx1 + len1] = data[:len1]

        len2 = frames - len1
        if len2 > 0:
            self.buffer[0:len2] = data[len1:]

        self.write_ptr = (self.write_ptr + frames) % self.capacity
        self.size += frames
        return frames

    def read(self, frames):
        if self.size == 0:
            return np.zeros((frames, self.channels), dtype=self.dtype), 0

        available = min(frames, self.size)

        out = np.zeros((frames, self.channels), dtype=self.dtype)

        idx1 = self.read_ptr
        len1 = min(available, self.capacity - idx1)
        out[:len1] = self.buffer[idx1 : idx1 + len1]

        len2 = available - len1
        if len2 > 0:
            out[len1:available] = self.buffer[0:len2]

        self.read_ptr = (self.read_ptr + available) % self.capacity
        self.size -= available

        return out, available

    def clear(self):
        self.read_ptr = 0
        self.write_ptr = 0
        self.size = 0
