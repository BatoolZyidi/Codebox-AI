"""Text-to-speech using the operating system's built-in voice (no extra downloads)."""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import sys
import time

from .config import Settings


def clean_for_speech(text: str) -> str:
    text = re.sub(r"[`*#_>|~]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:1500]


class Speaker:
    """Speaks text and reports whether it is (or was just) talking, so the
    microphone stream can ignore Codebox's own voice."""

    def __init__(self, settings: Settings, enabled: bool | None = None) -> None:
        self._s = settings
        self.enabled = settings.tts_enabled if enabled is None else enabled
        self._speaking = False
        self._last_end = -1e9
        self._lock = asyncio.Lock()
        self._proc: asyncio.subprocess.Process | None = None

    # -------------------------------------------------------------- status
    def active(self) -> bool:
        return self._speaking or (time.monotonic() - self._last_end) < self._s.echo_tail_seconds

    def engine_name(self) -> str | None:
        cmd = self._command("x")
        return cmd[0][0] if cmd else None

    # ------------------------------------------------------------- command
    def _command(self, text: str) -> tuple[list[str], dict[str, str], bytes | None] | None:
        rate = max(0.5, min(2.5, self._s.tts_rate))
        env = dict(os.environ)
        if sys.platform == "darwin" and shutil.which("say"):
            return ["say", "-r", str(round(175 * rate)), "-f", "-"], env, text.encode()
        if sys.platform.startswith("win"):
            shell = shutil.which("powershell") or shutil.which("pwsh")
            if shell:
                r = max(-10, min(10, round((rate - 1) * 10)))
                env["CODEBOX_TTS_TEXT"] = text
                script = (
                    "Add-Type -AssemblyName System.Speech; "
                    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                    f"$s.Rate = {r}; $s.Speak($env:CODEBOX_TTS_TEXT)"
                )
                return [shell, "-NoProfile", "-NonInteractive", "-Command", script], env, None
            return None
        for exe in ("espeak-ng", "espeak"):
            if shutil.which(exe):
                return [exe, "-s", str(round(160 * rate)), "--stdin"], env, text.encode()
        if shutil.which("spd-say"):
            return ["spd-say", "-w", "-r", str(round((rate - 1) * 100)), "--", text], env, None
        return None

    # --------------------------------------------------------------- speak
    async def say(self, text: str) -> None:
        text = clean_for_speech(text)
        if not text:
            return
        print(f"codebox> {text}", flush=True)
        if not self.enabled:
            return
        async with self._lock:
            spec = self._command(text)
            if spec is None:
                return
            argv, env, stdin_data = spec
            self._speaking = True
            try:
                kwargs: dict = {}
                if sys.platform.startswith("win"):
                    kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
                self._proc = await asyncio.create_subprocess_exec(
                    *argv,
                    stdin=asyncio.subprocess.PIPE if stdin_data is not None else asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                    env=env,
                    **kwargs,
                )
                await self._proc.communicate(stdin_data)
            except (OSError, asyncio.CancelledError):
                raise
            finally:
                if self._proc is not None and self._proc.returncode is None:
                    try:
                        self._proc.kill()
                    except ProcessLookupError:
                        pass
                self._proc = None
                self._speaking = False
                self._last_end = time.monotonic()

    def stop(self) -> None:
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.kill()
            except ProcessLookupError:
                pass
