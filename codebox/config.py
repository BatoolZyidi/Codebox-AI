"""Settings, loaded from environment variables or a .env file (see .env.example)."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(PROJECT_ROOT / ".env"), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- credentials ---
    assemblyai_api_key: str = ""
    gemini_api_key: str = ""

    # --- models / endpoints ---
    gemini_model: str = "gemini-3.5-flash-lite"
    assemblyai_ws_url: str = "wss://streaming.assemblyai.com/v3/ws"
    assemblyai_speech_model: str = ""  # empty = AssemblyAI's default streaming model

    # --- voice phrases ---
    wake_phrase: str = "wakeup codebox AI"
    close_phrase: str = "close yourself codebox AI"
    close_action: Literal["sleep", "exit"] = "sleep"
    idle_timeout_seconds: int = 0  # 0 = never go to sleep automatically

    # --- audio ---
    mic_device: str = ""  # empty = system default; or a device number / name fragment
    tts_enabled: bool = True
    tts_rate: float = 1.0  # 1.0 = normal speed
    echo_tail_seconds: float = 1.0  # ignore the mic this long after Codebox stops talking

    # --- repository / model limits ---
    codebox_repo: str = ""
    max_context_chars: int = 60000
    max_files_in_context: int = 8
    max_file_bytes: int = 512000
    max_indexed_files: int = 20000
    llm_timeout_seconds: int = 90


def load_settings() -> Settings:
    return Settings()
