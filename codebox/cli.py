"""Command-line entry point:  python -m codebox [run|chat|check|devices|index] [--repo PATH]"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from .assistant import Assistant
from .config import PROJECT_ROOT, Settings, load_settings
from .indexer import RepoIndex
from .search import build_keyterms
from .stt import FatalSTTError, StreamingSTT
from .tts import Speaker


def _require_keys(settings: Settings, need_stt: bool = True) -> None:
    missing = []
    if need_stt and not settings.assemblyai_api_key.strip():
        missing.append("ASSEMBLYAI_API_KEY")
    if not settings.gemini_api_key.strip():
        missing.append("GEMINI_API_KEY")
    if missing:
        sys.exit(
            f"Missing {', '.join(missing)}.\n"
            f"Copy .env.example to .env in {PROJECT_ROOT} and paste your keys there."
        )


def _make_index(settings: Settings, root: Path) -> RepoIndex:
    if not root.is_dir():
        sys.exit(f"Project folder not found: {root}")
    return RepoIndex(root, settings.max_file_bytes, settings.max_indexed_files)


# ------------------------------------------------------------------ voice mode
async def run_voice(settings: Settings, root: Path) -> None:
    from .audio import MicSource
    from .llm import GeminiLLM

    _require_keys(settings)
    loop = asyncio.get_running_loop()
    index = _make_index(settings, root)
    await asyncio.to_thread(index.refresh)
    print(f"Project: {root}  ({len(index.files)} files indexed)")

    speaker = Speaker(settings)
    if speaker.enabled and speaker.engine_name() is None:
        print("[warn] No text-to-speech engine found. On Linux install espeak-ng. Text will be printed only.")
    assistant = Assistant(settings, index, GeminiLLM(settings), speaker)
    queue: asyncio.Queue[str] = asyncio.Queue()

    mic = MicSource(loop, settings.mic_device)
    try:
        audio_queue = mic.start()
    except Exception as exc:
        sys.exit(f"Could not open the microphone: {exc}\nRun `python -m codebox devices` to see options.")

    base_terms = [settings.wake_phrase, settings.close_phrase, "Codebox AI", "undo", "apply", "reject"]
    announced = {"done": False}

    def on_connected() -> None:
        print("[stt] connected - listening.")
        if not announced["done"]:
            announced["done"] = True
            asyncio.get_running_loop().create_task(
                assistant.say(f"Codebox AI is ready. Say {settings.wake_phrase} to begin.")
            )

    stt = StreamingSTT(
        settings, audio_queue, speaker,
        keyterms=lambda: build_keyterms(index, base_terms),
        on_turn=queue.put_nowait,
        on_connected=on_connected,
    )
    tasks = [
        asyncio.create_task(stt.run(), name="stt"),
        asyncio.create_task(assistant.worker(queue), name="worker"),
        asyncio.create_task(assistant.idle_watch(), name="idle"),
        asyncio.create_task(assistant.stop_event.wait(), name="stop"),
    ]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            if not t.cancelled() and t.exception():
                raise t.exception()  # type: ignore[misc]
    finally:
        stt.stop()
        mic.stop()
        speaker.stop()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


# ------------------------------------------------------------------- chat mode
async def run_chat(settings: Settings, root: Path, speak: bool) -> None:
    from .llm import GeminiLLM

    _require_keys(settings, need_stt=False)
    index = _make_index(settings, root)
    await asyncio.to_thread(index.refresh)
    print(f"Project: {root}  ({len(index.files)} files indexed)")
    assistant = Assistant(settings, index, GeminiLLM(settings), Speaker(settings, enabled=speak))
    assistant.awake = True
    print('Type what you would say. Type "quit" to leave. (Wake and close phrases work here too.)')
    while not assistant.stop_event.is_set():
        try:
            line = await asyncio.to_thread(input, "> ")
        except EOFError:
            break
        if line.strip().lower() in {"quit", "exit"}:
            break
        await assistant.handle(line)


# ----------------------------------------------------------------------- check
async def run_check(settings: Settings) -> int:
    ok = True

    def report(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))

    report("ASSEMBLYAI_API_KEY set", bool(settings.assemblyai_api_key.strip()))
    report("GEMINI_API_KEY set", bool(settings.gemini_api_key.strip()))

    # microphone
    try:
        import sounddevice as sd

        dev = sd.query_devices(kind="input")
        report("Microphone found", True, dev["name"])
    except Exception as exc:
        report("Microphone found", False, str(exc))

    # text to speech
    sp = Speaker(settings)
    engine = sp.engine_name()
    report("Text-to-speech engine", engine is not None, engine or "install espeak-ng (Linux)")
    if engine:
        await sp.say("Codebox AI speech test.")

    # Gemini
    if settings.gemini_api_key.strip():
        try:
            from .llm import GeminiLLM

            reply = await asyncio.wait_for(
                asyncio.to_thread(GeminiLLM(settings).complete, "Reply with the JSON {\"kind\":\"answer\",\"spoken\":\"ok\"}"),
                timeout=45,
            )
            report(f"Gemini ({settings.gemini_model})", bool(reply.strip()), "responded")
        except Exception as exc:
            report(f"Gemini ({settings.gemini_model})", False, str(exc)[:200])

    # AssemblyAI
    if settings.assemblyai_api_key.strip():
        import websockets

        url = f"{settings.assemblyai_ws_url}?sample_rate=16000&encoding=pcm_s16le"
        try:
            ws = await asyncio.wait_for(
                websockets.connect(url, additional_headers={"Authorization": settings.assemblyai_api_key}),
                timeout=20,
            )
            try:
                first = await asyncio.wait_for(ws.recv(), timeout=15)
                report("AssemblyAI streaming", '"Begin"' in str(first), "session started")
            finally:
                await ws.close()
        except Exception as exc:
            report("AssemblyAI streaming", False, str(exc)[:200])

    print("\nAll good - run:  python -m codebox run --repo <your project folder>" if ok
          else "\nFix the FAIL lines above, then run this check again.")
    return 0 if ok else 1


# ------------------------------------------------------------------------ main
def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="codebox", description="Codebox AI - talk to your codebase.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "chat", "check", "devices", "index"],
                        help="run = voice mode (default); chat = typed mode; check = test setup; "
                             "devices = list microphones; index = show what will be searched")
    parser.add_argument("--repo", help="project folder to work on (default: current folder)")
    parser.add_argument("--speak", action="store_true", help="chat mode: also speak replies")
    args = parser.parse_args(argv)

    settings = load_settings()
    root = Path(args.repo or settings.codebox_repo or os.getcwd()).expanduser().resolve()

    try:
        if args.command == "devices":
            from .audio import list_devices

            print(list_devices())
        elif args.command == "index":
            idx = _make_index(settings, root)
            idx.refresh()
            n_sym = sum(len(f.symbols) for f in idx.files.values())
            print(f"{root}\n{len(idx.files)} files, {n_sym} symbols indexed")
            for p in idx.tree(40):
                print("  " + p)
        elif args.command == "check":
            sys.exit(asyncio.run(run_check(settings)))
        elif args.command == "chat":
            asyncio.run(run_chat(settings, root, args.speak))
        else:
            asyncio.run(run_voice(settings, root))
    except FatalSTTError as exc:
        sys.exit(f"\n{exc}")
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
