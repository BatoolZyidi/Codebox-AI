"""Microphone capture: 16 kHz, 16-bit, mono PCM in 50 ms chunks."""
from __future__ import annotations

import asyncio

SAMPLE_RATE = 16000
BLOCK_FRAMES = 800  # 50 ms


def _device(value: str):  # type: ignore[no-untyped-def]
    value = (value or "").strip()
    if not value:
        return None
    return int(value) if value.isdigit() else value


def list_devices() -> str:
    import sounddevice as sd

    return str(sd.query_devices())


class MicSource:
    def __init__(self, loop: asyncio.AbstractEventLoop, device: str = "") -> None:
        self._loop = loop
        self._device = _device(device)
        self.queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=200)  # ~10 s of audio
        self._stream = None

    def _push(self, data: bytes) -> None:
        if self.queue.full():
            self.queue.get_nowait()  # drop the oldest chunk
        self.queue.put_nowait(data)

    def _callback(self, indata, frames, time_info, status) -> None:  # type: ignore[no-untyped-def]
        try:
            self._loop.call_soon_threadsafe(self._push, bytes(indata))
        except RuntimeError:
            pass  # event loop already closed

    def start(self) -> asyncio.Queue[bytes]:
        import sounddevice as sd

        self._stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_FRAMES,
            channels=1,
            dtype="int16",
            device=self._device,
            callback=self._callback,
        )
        self._stream.start()
        return self.queue

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None
