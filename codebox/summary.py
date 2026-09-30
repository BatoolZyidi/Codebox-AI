"""Turns a planned change into short, plain-English text meant to be heard."""
from __future__ import annotations

from .edits import FileChange, line_stats, preview


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _labels(changes: list[FileChange]) -> dict[str, str]:
    names = [c.path.split("/")[-1] for c in changes]
    out = {}
    for c, name in zip(changes, names):
        if names.count(name) > 1:
            out[c.path] = "/".join(c.path.split("/")[-2:])
        else:
            out[c.path] = name
    return out


def summarize(changes: list[FileChange], spoken: str = "") -> str:
    label = _labels(changes)
    edited = [c for c in changes if not c.created]
    created = [c for c in changes if c.created]
    parts: list[str] = []
    if spoken.strip():
        parts.append(spoken.strip().rstrip(".") + ".")
    if edited:
        items = ", ".join(f"{label[c.path]} in {_plural(c.places, 'place')}" for c in edited)
        parts.append(f"This will change {_plural(len(edited), 'file')}: {items}.")
    if created:
        parts.append("It will create " + ", ".join(label[c.path] for c in created) + ".")
    added, removed = line_stats(changes)
    parts.append(f"Overall, {_plural(added, 'line')} added and {_plural(removed, 'line')} removed.")
    parts.append("Say apply, reject, details, or read it again.")
    return " ".join(parts)


def details(changes: list[FileChange]) -> str:
    label = _labels(changes)
    out: list[str] = []
    for c in changes:
        for old, new in c.notes:
            if old == "":
                out.append(f"In {label[c.path]}: create the file, starting with {preview(new)}.")
            else:
                out.append(f"In {label[c.path]}: replace {preview(old)} with {preview(new) or 'nothing'}.")
    out.append("Say apply or reject.")
    return " ".join(out)
