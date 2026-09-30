import asyncio
import os
import stat
import sys

from codebox.tts import Speaker, clean_for_speech
from tests.helpers import make_settings


def test_clean_for_speech():
    assert clean_for_speech("Use `get_user` **now**\n\n# ok") == "Use get user now ok"


def test_speaker_pipes_text_and_tracks_active(tmp_path, monkeypatch):
    if sys.platform.startswith("win"):
        return
    out = tmp_path / "spoken.txt"
    fake = tmp_path / "espeak-ng"
    fake.write_text(f"#!/bin/sh\ncat > {out}\nsleep 0.2\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(sys, "platform", "linux")

    async def go():
        sp = Speaker(make_settings(tts_enabled=True, echo_tail_seconds=0.3))
        assert sp.engine_name() == "espeak-ng" and not sp.active()
        task = asyncio.create_task(sp.say("Hello from Codebox"))
        await asyncio.sleep(0.1)
        assert sp.active()          # talking
        await task
        assert sp.active()          # echo tail still applies
        await asyncio.sleep(0.4)
        assert not sp.active()

    asyncio.run(go())
    assert out.read_text() == "Hello from Codebox"


def test_command_shapes(monkeypatch):
    import shutil
    s = Speaker(make_settings(tts_enabled=True, tts_rate=1.0))
    monkeypatch.setattr(shutil, "which", lambda n: f"/x/{n}" if n in ("say", "powershell") else None)
    monkeypatch.setattr(sys, "platform", "darwin")
    argv, _, stdin = s._command("hi")
    assert argv[0] == "say" and stdin == b"hi"
    monkeypatch.setattr(sys, "platform", "win32")
    argv, env, stdin = s._command("it's \"quoted\"")
    assert argv[0].endswith("powershell") and env["CODEBOX_TTS_TEXT"] == "it's \"quoted\"" and stdin is None
    monkeypatch.setattr(shutil, "which", lambda n: None)
    monkeypatch.setattr(sys, "platform", "linux")
    assert s._command("hi") is None
