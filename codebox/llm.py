"""Gemini integration: prompt building, the API call, and strict parsing of the reply."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Protocol

from .config import Settings
from .edits import Edit
from .indexer import RepoIndex
from .search import Hit

SYSTEM_PROMPT = """\
You are Codebox AI, a voice coding assistant used mainly by blind and motor-impaired developers.
Everything you put in "spoken" is read aloud by a text-to-speech engine.

You receive a repository tree, relevant symbols, the contents of relevant files, the recent
conversation, and the user's request. The request comes from speech recognition, so code names may
be misspelled or split into words (for example "get user" for getUser). Map them to the closest real
symbol in the material provided.

Reply with ONE JSON object and nothing else:
{
  "kind": "answer" | "change" | "clarify",
  "spoken": "text to read aloud",
  "edits": [ {"path": "relative/posix/path", "old": "exact existing text", "new": "replacement text", "replace_all": false} ]
}

Rules:
- "answer": the user asked a question or wants an explanation. "edits" must be [].
- "change": the user asked to modify code. Provide "edits".
- "clarify": the request is too ambiguous to act on safely. Ask ONE short question in "spoken"; "edits" must be [].
- "spoken" is plain conversational English: no markdown, no code blocks, no symbols read out. Answers: at most 80 words.
  Changes: at most 40 words saying what will change and why.
- Name files by file name (add the folder only if ambiguous) and code by its spoken name.
- Each edit replaces text that exists in a provided file. "old" must be copied EXACTLY (whitespace and indentation
  included), contiguous, and unique in that file unless "replace_all" is true. Add surrounding lines to make it unique.
  Never include line numbers or "omitted" markers.
- To create a new file use "old": "" and put the entire file in "new".
- Use "replace_all": true only for renames where every occurrence of "old" in that file should change.
- Keep edits minimal. Do not reformat unrelated code. Only edit files that were shown to you.
  Never touch secrets, environment files, or the .git folder.
- If the provided files are not enough to make the change, use "clarify" and say what you need.
"""

_VALID_KINDS = {"answer", "change", "clarify"}


class LLMClient(Protocol):
    def complete(self, prompt: str) -> str: ...


class GeminiLLM:
    def __init__(self, settings: Settings) -> None:
        from google import genai
        from google.genai import types

        self._types = types
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_model

    def complete(self, prompt: str) -> str:
        cfg = self._types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.2,
            response_mime_type="application/json",
        )
        resp = self._client.models.generate_content(model=self._model, contents=prompt, config=cfg)
        return resp.text or ""


@dataclass
class LLMResult:
    kind: str
    spoken: str
    edits: list[Edit] = field(default_factory=list)


def parse_result(raw: str) -> LLMResult:
    text = (raw or "").strip()
    if not text:
        raise ValueError("The model returned an empty reply.")
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("The model reply was not valid JSON.") from None
        try:
            data = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            raise ValueError("The model reply was not valid JSON.") from None
    if not isinstance(data, dict):
        raise ValueError("The model reply was not a JSON object.")

    edits: list[Edit] = []
    for item in data.get("edits") or []:
        if not isinstance(item, dict) or "path" not in item:
            raise ValueError("An edit was missing its file path.")
        edits.append(
            Edit(
                path=str(item["path"]),
                old=str(item.get("old") or ""),
                new=str(item.get("new") or ""),
                replace_all=bool(item.get("replace_all", False)),
            )
        )
    kind = str(data.get("kind", "")).lower()
    if kind not in _VALID_KINDS:
        kind = "change" if edits else "answer"
    if kind == "change" and not edits:
        raise ValueError("The model said it would change code but gave no edits.")
    spoken = str(data.get("spoken") or "").strip()
    return LLMResult(kind, spoken, edits if kind == "change" else [])


# ----------------------------------------------------------------- prompting
def _excerpt(text: str, lines: list[int], limit: int, radius: int = 25) -> tuple[str, str]:
    src = text.split("\n")
    if not lines:
        return text[:limit], f"first {min(len(text), limit)} characters"
    spans: list[list[int]] = []
    for ln in sorted(set(lines)):
        lo, hi = max(1, ln - radius), min(len(src), ln + radius)
        if spans and lo <= spans[-1][1] + 1:
            spans[-1][1] = max(spans[-1][1], hi)
        else:
            spans.append([lo, hi])
    out: list[str] = []
    used = 0
    for lo, hi in spans:
        chunk = "\n".join(src[lo - 1:hi])
        if used and used + len(chunk) > limit:
            break
        out.append(f"# ... lines omitted before {lo} ...\n{chunk}" if lo > 1 else chunk)
        used += len(chunk)
    return "\n".join(out), "excerpts only"


def build_context(
    index: RepoIndex, hits: list[Hit], per_file_chars: int = 20000, total_chars: int = 60000
) -> str:
    blocks: list[str] = []
    used = 0
    for h in hits:
        text = index.read(h.path)
        if text is None:
            continue
        if len(text) <= per_file_chars:
            body, label = text, "full file"
        else:
            body, label = _excerpt(text, h.lines, per_file_chars)
        block = f"=== FILE: {h.path} ({label}) ===\n{body}\n=== END FILE ===\n"
        if blocks and used + len(block) > total_chars:
            break
        blocks.append(block)
        used += len(block)
    return "\n".join(blocks) if blocks else "(no relevant files found)"


def build_prompt(
    request: str,
    index: RepoIndex,
    hits: list[Hit],
    history: list[tuple[str, str]],
    max_context_chars: int = 60000,
) -> str:
    symbols: list[str] = []
    for h in hits:
        for s in h.symbols[:10]:
            symbols.append(f"{s.kind} {s.qual or s.name}  ({s.path}:{s.line})")
    convo = "\n".join(f"User: {u}\nCodebox: {a}" for u, a in history[-4:]) or "(none)"
    return (
        f"PROJECT FOLDER: {index.root.name}\n\n"
        f"REPOSITORY FILES:\n" + "\n".join(index.tree()) + "\n\n"
        f"RELEVANT SYMBOLS:\n" + ("\n".join(symbols[:40]) or "(none matched)") + "\n\n"
        f"FILE CONTENTS:\n{build_context(index, hits, total_chars=max_context_chars)}\n\n"
        f"RECENT CONVERSATION:\n{convo}\n\n"
        f"USER REQUEST (from speech recognition):\n{request}\n"
    )
