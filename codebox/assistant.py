"""The assistant: wake/sleep state machine, voice commands, and the request pipeline."""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .config import Settings
from .edits import (
    EditError, FileChange, apply_changes, plan_changes, save_patch, undo_last,
)
from .indexer import RepoIndex
from .llm import LLMClient, LLMResult, build_prompt, parse_result
from .search import retrieve
from .summary import details, summarize

HELP_TEXT = (
    "You can ask questions about your code, like: where is login handled? "
    "Or ask for a change, like: rename get user to fetch user everywhere. "
    "After I describe a change, say apply, reject, details, or read it again. "
    "Say undo to reverse the last change. "
    "Say {close} to put me to sleep."
)

_FILLER_END = r"( please)?"
_RX = {
    "apply": re.compile(rf"^(please )?(apply|yes|confirm|go ahead|do it|approve)( it| that| this| the changes?| changes?)?{_FILLER_END}$"),
    "reject": re.compile(rf"^(please )?(reject|cancel|discard|no|nope|never ?mind|don'?t apply|do not apply)( it| that| this| the changes?| changes?)?{_FILLER_END}$"),
    "repeat": re.compile(rf"^(please )?(read (it|that|this) again|read again|repeat( that| it)?|say (it|that) again|again){_FILLER_END}$"),
    "details": re.compile(rf"^(please )?((show|read|tell me|give me)( me)?( the)? )?((more )?details|tell me more){_FILLER_END}$"),
    "undo": re.compile(rf"^(please )?(undo|revert)( that| it| this| the last change| last change| the change)?{_FILLER_END}$"),
    "help": re.compile(r"^(help|what can you do|what can i say|commands|instructions)$"),
}


def classify(text: str) -> str:
    """Map a spoken utterance to a control command, or 'request' for anything else."""
    t = re.sub(r"[^a-z' ]", " ", text.lower())
    t = " ".join(t.split())
    for name, rx in _RX.items():
        if rx.match(t):
            return name
    return "request"


class _Speaker(Protocol):
    async def say(self, text: str) -> None: ...


@dataclass
class Pending:
    changes: list[FileChange]
    summary: str
    details: str


class Assistant:
    def __init__(
        self,
        settings: Settings,
        index: RepoIndex,
        llm: LLMClient,
        speaker: _Speaker,
    ) -> None:
        from .wake import PhraseMatcher

        self.s = settings
        self.index = index
        self.root: Path = index.root
        self.llm = llm
        self.speaker = speaker
        self.awake = False
        self.pending: Pending | None = None
        self.history: list[tuple[str, str]] = []
        self.recent_paths: list[str] = []
        self.last_spoken = ""
        self.stop_event = asyncio.Event()
        self._wake = PhraseMatcher(settings.wake_phrase)
        self._close = PhraseMatcher(settings.close_phrase)
        self._activity = time.monotonic()
        self._busy = False

    # -------------------------------------------------------------- plumbing
    async def say(self, text: str) -> None:
        self.last_spoken = text
        await self.speaker.say(text)

    async def worker(self, queue: "asyncio.Queue[str]") -> None:
        """Handle transcripts one at a time; never let one failure stop the loop."""
        while True:
            text = await queue.get()
            try:
                await self.handle(text)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # last-resort safety net
                print(f"[error] {exc!r}")
                await self.say("Sorry, something went wrong. Nothing was changed.")

    async def idle_watch(self) -> None:
        limit = self.s.idle_timeout_seconds
        if limit <= 0:
            await asyncio.Event().wait()  # disabled: sleep forever
        while True:
            await asyncio.sleep(5)
            if self.awake and not self._busy and time.monotonic() - self._activity > limit:
                await self._sleep("I haven't heard anything for a while, so I'm going to sleep.")

    # ---------------------------------------------------------------- routing
    async def handle(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if not self.awake:
            ok, rest = self._wake.find(text)
            if not ok:
                return  # ignore everything until the wake phrase
            self.awake = True
            self._activity = time.monotonic()
            if len(rest.split()) >= 2:
                await self.say("Awake.")
                await self._handle_awake(rest)
            else:
                await self.say("Codebox AI is awake. How can I help?")
            return
        await self._handle_awake(text)

    async def _handle_awake(self, text: str) -> None:
        self._activity = time.monotonic()
        print(f"you> {text}", flush=True)
        if self._close.find(text)[0]:
            await self._close_now()
            return
        if self._wake.find(text)[0]:
            await self.say("I'm already awake.")
            return
        cmd = classify(text)
        if cmd == "help":
            await self.say(HELP_TEXT.format(close=self.s.close_phrase))
        elif cmd == "undo":
            await self._undo()
        elif cmd in ("apply", "reject", "details"):
            if self.pending is None:
                await self.say("There is no pending change.")
            elif cmd == "apply":
                await self._apply()
            elif cmd == "reject":
                self.pending = None
                await self.say("Discarded. Nothing was changed.")
            else:
                await self.say(self.pending.details)
        elif cmd == "repeat":
            if self.pending:
                await self.say(self.pending.summary)
            else:
                await self.say(self.last_spoken or "There is nothing to repeat yet.")
        elif self.pending is not None:
            await self.say(
                "There is a pending change. Say apply, reject, details, or read it again. "
                "To start something new, say reject first."
            )
        else:
            await self._request(text)

    # --------------------------------------------------------- sleep / close
    async def _close_now(self) -> None:
        self.pending = None
        if self.s.close_action == "exit":
            await self.say("Goodbye.")
            self.stop_event.set()
        else:
            await self._sleep(f"Going to sleep. Say {self.s.wake_phrase} to wake me.")

    async def _sleep(self, message: str) -> None:
        self.awake = False
        self.pending = None
        await self.say(message)

    # ------------------------------------------------------------ the pipeline
    async def _call_llm(self, prompt: str) -> str:
        return await asyncio.wait_for(
            asyncio.to_thread(self.llm.complete, prompt), timeout=self.s.llm_timeout_seconds
        )

    async def _working_notice(self) -> None:
        await asyncio.sleep(3)
        await self.say("Working on it.")

    async def _request(self, text: str) -> None:
        self._busy = True
        notice = asyncio.create_task(self._working_notice())
        try:
            result, changes = await self._ask(text)
        except asyncio.TimeoutError:
            notice.cancel()
            await self.say("The AI took too long to answer. Please try again.")
            return
        except EditError as exc:
            notice.cancel()
            await self.say(f"I couldn't prepare a safe change. {str(exc)[:200]} Nothing was changed.")
            return
        except Exception as exc:
            notice.cancel()
            print(f"[error] {exc!r}")
            await self.say(f"I couldn't reach the AI service. {str(exc)[:160]}")
            return
        finally:
            self._busy = False
            if not notice.done():
                notice.cancel()
            await asyncio.gather(notice, return_exceptions=True)

        if result.kind == "change" and changes:
            summary = summarize(changes, result.spoken)
            self.pending = Pending(changes, summary, details(changes))
            self.recent_paths = [c.path for c in changes]
            try:
                save_patch(self.root, changes)
            except OSError:
                pass
            self.history.append((text, result.spoken))
            await self.say(summary)
        else:
            reply = result.spoken or "I don't have an answer for that."
            self.history.append((text, reply))
            await self.say(reply)
        self.history = self.history[-6:]

    async def _ask(self, text: str) -> tuple[LLMResult, list[FileChange] | None]:
        await asyncio.to_thread(self.index.refresh)
        hits = await asyncio.to_thread(
            retrieve, self.index, text, self.recent_paths, self.s.max_files_in_context
        )
        prompt = build_prompt(text, self.index, hits, self.history, self.s.max_context_chars)
        error: str | None = None
        for _ in range(2):
            p = prompt if error is None else (
                f"{prompt}\nYOUR PREVIOUS ANSWER WAS REJECTED: {error}\n"
                "Return corrected JSON only, copying 'old' text exactly from the files above."
            )
            try:
                result = parse_result(await self._call_llm(p))
                if result.kind == "change":
                    return result, plan_changes(self.root, result.edits)
                return result, None
            except ValueError as exc:  # includes EditError
                error = str(exc)
        raise EditError(error or "The AI reply could not be used.")

    # ----------------------------------------------------------- apply / undo
    async def _apply(self) -> None:
        assert self.pending is not None
        changes = self.pending.changes
        try:
            await asyncio.to_thread(apply_changes, self.root, changes)
        except Exception as exc:
            print(f"[error] {exc!r}")
            self.pending = None
            await self.say("I couldn't write the changes, so I put everything back. Nothing was changed.")
            return
        self.pending = None
        await asyncio.to_thread(self.index.refresh)
        n = len(changes)
        await self.say(f"Done. I changed {n} file{'s' if n != 1 else ''}. Say undo to reverse it.")

    async def _undo(self) -> None:
        self.pending = None
        result = await asyncio.to_thread(undo_last, self.root)
        if result is None:
            await self.say("There is nothing to undo.")
            return
        restored, skipped = result
        await asyncio.to_thread(self.index.refresh)
        msg = f"Undone. I restored {len(restored)} file{'s' if len(restored) != 1 else ''}."
        if skipped:
            msg += f" I left {len(skipped)} file{'s' if len(skipped) != 1 else ''} alone because you changed them since."
        await self.say(msg)
