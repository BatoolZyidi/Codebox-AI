import asyncio
import json

import pytest
import websockets

from codebox.stt import FatalSTTError, StreamingSTT
from tests.helpers import make_settings


class Quiet:
    def __init__(self, active=False):
        self._a = active

    def active(self):
        return self._a


def run_against_server(handler, speaker=None, keyterms=None, wait=1.5, http_reject=None):
    got_turns, connected, urls, chunks = [], [], [], []

    async def go():
        async def h(ws):
            urls.append(ws.request.path)
            urls.append(ws.request.headers.get("Authorization"))
            await handler(ws, chunks)

        async def process_request(connection, request):
            if http_reject:
                return connection.respond(http_reject, "no")

        async with websockets.serve(h, "127.0.0.1", 0, process_request=process_request) as server:
            port = server.sockets[0].getsockname()[1]
            s = make_settings(assemblyai_ws_url=f"ws://127.0.0.1:{port}/v3/ws", assemblyai_api_key="KEY123")
            q = asyncio.Queue()

            async def mic():  # a live microphone keeps producing chunks
                while True:
                    q.put_nowait(b"\x01\x02" * 800)
                    await asyncio.sleep(0.02)

            feeder = asyncio.create_task(mic())
            stt = StreamingSTT(s, q, speaker or Quiet(), keyterms or (lambda: ["Codebox AI", "login service"]),
                               got_turns.append, lambda: connected.append(1), log=lambda m: None)
            task = asyncio.create_task(stt.run())
            try:
                await asyncio.wait_for(task, timeout=wait)
            except asyncio.TimeoutError:
                pass
            finally:
                stt.stop()
                feeder.cancel()
                task.cancel()
                await asyncio.gather(task, feeder, return_exceptions=True)

    asyncio.run(go())
    return got_turns, connected, urls, chunks


async def happy_handler(ws, chunks):
    await ws.send(json.dumps({"type": "Begin", "id": "abc", "expires_at": 1}))
    n = 0
    async for m in ws:
        if isinstance(m, bytes):
            chunks.append(m)
            n += 1
            if n == 2:
                await ws.send(json.dumps({"type": "Turn", "turn_order": 0, "transcript": "wake", "end_of_turn": False}))
                await ws.send(json.dumps({"type": "Turn", "turn_order": 0, "transcript": "wakeup codebox AI", "end_of_turn": True}))
                # duplicate (formatted) copy of the same turn must be ignored
                await ws.send(json.dumps({"type": "Turn", "turn_order": 0, "transcript": "Wakeup Codebox AI.", "end_of_turn": True, "turn_is_formatted": True}))


def test_streams_audio_and_delivers_each_turn_once():
    turns, connected, urls, chunks = run_against_server(happy_handler)
    assert turns == ["wakeup codebox AI"]
    assert connected and len(chunks) >= 2 and len(chunks[0]) == 1600
    assert urls[1] == "KEY123"
    assert "sample_rate=16000" in urls[0] and "keyterms_prompt=" in urls[0] and "format_turns=false" in urls[0]


def test_ignores_own_voice_and_sends_silence_while_speaking():
    turns, _, _, chunks = run_against_server(happy_handler, speaker=Quiet(active=True))
    assert turns == []
    assert chunks and all(c == bytes(1600) for c in chunks)


def test_bad_api_key_is_fatal():
    async def unused(ws, chunks):
        pass

    with pytest.raises(FatalSTTError, match="401"):
        run_against_server(unused, http_reject=401, wait=5)


def test_reconnects_after_server_drops_and_retries_without_keyterms():
    attempts = []

    async def flaky(ws, chunks):
        attempts.append(ws.request.path)
        if len(attempts) == 1:
            await ws.close(code=1011)  # server error right after connect
            return
        await happy_handler(ws, chunks)

    turns, _, _, _ = run_against_server(flaky, wait=6)
    assert len(attempts) >= 2
    assert "keyterms_prompt" in attempts[0] and "keyterms_prompt" not in attempts[1]
    assert turns == ["wakeup codebox AI"]
