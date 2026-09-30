"""AssemblyAI streaming speech-to-text (v3 WebSocket API) with auto-reconnect."""
from __future__ import annotations

import asyncio
import json
import time
import urllib.parse
from typing import Callable, Protocol

import websockets
from websockets.exceptions import InvalidStatus

from .config import Settings


class FatalSTTError(RuntimeError):
    """Something retrying cannot fix (bad API key, no credit...)."""


class _SpeakerLike(Protocol):
    def active(self) -> bool: ...


class StreamingSTT:
    """Streams microphone audio to AssemblyAI and calls `on_turn(text)` for every
    finished utterance.

    While Codebox itself is speaking, silence is sent instead of the microphone,
    and any transcript that arrives is dropped, so it never hears itself.
    """

    def __init__(
        self,
        settings: Settings,
        audio_queue: "asyncio.Queue[bytes]",
        speaker: _SpeakerLike,
        keyterms: Callable[[], list[str]],
        on_turn: Callable[[str], None],
        on_connected: Callable[[], None] | None = None,
        log: Callable[[str], None] = print,
    ) -> None:
        self._s = settings
        self._audio = audio_queue
        self._speaker = speaker
        self._keyterms = keyterms
        self._on_turn = on_turn
        self._on_connected = on_connected
        self._log = log
        self._stop = False
        self._seen_turns: set[object] = set()
        self._used_keyterms = False

    def stop(self) -> None:
        self._stop = True

    # --------------------------------------------------------------- lifecycle
    async def run(self) -> None:
        backoff = 1.0
        use_keyterms = True
        while not self._stop:
            started = time.monotonic()
            try:
                await self._session(use_keyterms)
                backoff = 1.0
                await asyncio.sleep(0.5)
            except (FatalSTTError, asyncio.CancelledError):
                raise
            except Exception as exc:  # network drop, server close, ...
                if self._stop:
                    return
                if use_keyterms and self._used_keyterms and time.monotonic() - started < 5:
                    self._log("[stt] keyterm boosting was rejected; continuing without it.")
                    use_keyterms = False
                self._log(f"[stt] connection problem ({exc!r}). Retrying in {backoff:.0f}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 15.0)

    def _url(self, use_keyterms: bool) -> str:
        params = {"sample_rate": "16000", "encoding": "pcm_s16le", "format_turns": "false"}
        if self._s.assemblyai_speech_model:
            params["speech_model"] = self._s.assemblyai_speech_model
        terms = self._keyterms() if use_keyterms else []
        self._used_keyterms = bool(terms)
        if terms:
            params["keyterms_prompt"] = json.dumps(terms)
        sep = "&" if "?" in self._s.assemblyai_ws_url else "?"
        return f"{self._s.assemblyai_ws_url}{sep}{urllib.parse.urlencode(params)}"

    async def _session(self, use_keyterms: bool) -> None:
        url = self._url(use_keyterms)
        headers = {"Authorization": self._s.assemblyai_api_key}
        self._seen_turns.clear()
        try:
            conn = websockets.connect(url, additional_headers=headers, max_size=None)
            ws = await conn
        except InvalidStatus as exc:
            code = getattr(getattr(exc, "response", None), "status_code", None)
            if code in (401, 402, 403):
                raise FatalSTTError(
                    f"AssemblyAI refused the connection (HTTP {code}). "
                    "Check ASSEMBLYAI_API_KEY and your account credit."
                ) from None
            raise
        try:
            while not self._audio.empty():  # drop audio captured while disconnected
                self._audio.get_nowait()
            sender = asyncio.create_task(self._send_loop(ws))
            try:
                async for message in ws:
                    self._handle(message)
                    if sender.done():
                        break
            finally:
                sender.cancel()
                await asyncio.gather(sender, return_exceptions=True)
        finally:
            try:
                await ws.send(json.dumps({"type": "Terminate"}))
            except Exception:
                pass
            await ws.close()

    async def _send_loop(self, ws) -> None:  # type: ignore[no-untyped-def]
        while True:
            chunk = await self._audio.get()
            if self._speaker.active():
                chunk = bytes(len(chunk))  # silence, keeps the session alive
            await ws.send(chunk)

    # ---------------------------------------------------------------- messages
    def _handle(self, raw: object) -> None:
        if isinstance(raw, bytes):
            return
        try:
            msg = json.loads(raw)  # type: ignore[arg-type]
        except (TypeError, json.JSONDecodeError):
            return
        kind = msg.get("type")
        if kind == "Begin":
            if self._on_connected:
                self._on_connected()
        elif kind == "Turn":
            text = (msg.get("transcript") or "").strip()
            if not text or not msg.get("end_of_turn"):
                return
            order = msg.get("turn_order")
            if order is not None:
                if order in self._seen_turns:
                    return
                self._seen_turns.add(order)
            if self._speaker.active():
                return  # that was probably our own voice
            self._on_turn(text)
        elif kind in ("Error", "error") or "error" in msg:
            self._log(f"[stt] server message: {msg}")
