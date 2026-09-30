"""Safe code changes: plan (dry run) -> diff -> apply with backup -> undo.

The LLM proposes *exact-text replacements*. We validate them against the real
files, build a unified diff ourselves, and only write to disk after the user
says "apply". Every apply is backed up so "undo" works.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .safety import PROTECTED_DIRS, is_sensitive


class EditError(ValueError):
    """A proposed change is invalid or unsafe. Nothing was modified."""


@dataclass
class Edit:
    path: str
    old: str
    new: str
    replace_all: bool = False


@dataclass
class FileChange:
    path: str
    before: str | None  # None = new file
    after: str
    places: int
    crlf: bool = False
    notes: list[tuple[str, str]] = field(default_factory=list)

    @property
    def created(self) -> bool:
        return self.before is None

    def encoded(self) -> bytes:
        text = self.after.replace("\n", "\r\n") if self.crlf else self.after
        return text.encode("utf-8")


def preview(text: str, limit: int = 80) -> str:
    for line in text.splitlines():
        if line.strip():
            line = line.strip()
            return line if len(line) <= limit else line[: limit - 3] + "..."
    return ""


def resolve_inside(root: Path, rel: str) -> Path:
    rel = (rel or "").replace("\\", "/").strip()
    if not rel or rel.startswith(("/", "~")) or ":" in rel.split("/")[0]:
        raise EditError(f"Unsafe file path: {rel!r}")
    base = root.resolve()
    target = (base / rel).resolve()
    try:
        parts = target.relative_to(base).parts
    except ValueError:
        raise EditError(f"{rel!r} is outside the project folder.") from None
    if not parts:
        raise EditError("Cannot edit the project folder itself.")
    if any(p in PROTECTED_DIRS for p in parts[:-1]) or is_sensitive(parts[-1]):
        raise EditError(f"{rel} is protected and will not be changed.")
    return target


def plan_changes(root: Path, edits: list[Edit]) -> list[FileChange]:
    """Dry run. Returns the resulting file contents, or raises EditError."""
    if not edits:
        raise EditError("No edits were proposed.")
    base = Path(root).resolve()
    grouped: dict[str, list[Edit]] = {}
    for e in edits:
        rel = resolve_inside(base, e.path).relative_to(base).as_posix()
        grouped.setdefault(rel, []).append(e)

    changes: list[FileChange] = []
    for rel, elist in grouped.items():
        full = base / rel
        before: str | None = None
        crlf = False
        if full.exists():
            if not full.is_file():
                raise EditError(f"{rel} is not a file.")
            try:
                raw = full.read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                raise EditError(f"{rel} is not a UTF-8 text file.") from None
            crlf = "\r\n" in raw
            before = raw.replace("\r\n", "\n")
        current = before
        places = 0
        notes: list[tuple[str, str]] = []
        for e in elist:
            old = e.old.replace("\r\n", "\n")
            new = e.new.replace("\r\n", "\n")
            if old == "":
                if current is None or current == "":
                    current, places = new, places + 1
                    notes.append(("", new))
                    continue
                raise EditError(f"{rel} already exists. Give the exact existing text to replace.")
            if current is None:
                raise EditError(f"{rel} does not exist.")
            n = current.count(old)
            if n == 0:
                raise EditError(f"In {rel}, this text was not found exactly: {preview(old)!r}")
            if n > 1 and not e.replace_all:
                raise EditError(
                    f"In {rel}, this text appears {n} times: {preview(old)!r}. "
                    "Include more surrounding lines, or set replace_all."
                )
            current = current.replace(old, new) if e.replace_all else current.replace(old, new, 1)
            places += n if e.replace_all else 1
            notes.append((old, new))
        if current != before and current is not None:
            changes.append(FileChange(rel, before, current, places, crlf, notes))
    if not changes:
        raise EditError("The proposed edits would not change anything.")
    return changes


def unified_diff(changes: list[FileChange]) -> str:
    out: list[str] = []
    for ch in changes:
        a = [] if ch.before is None else ch.before.splitlines(keepends=True)
        b = ch.after.splitlines(keepends=True)
        for line in difflib.unified_diff(
            a, b,
            fromfile="/dev/null" if ch.before is None else f"a/{ch.path}",
            tofile=f"b/{ch.path}",
        ):
            out.append(line if line.endswith("\n") else line + "\n")
    return "".join(out)


def line_stats(changes: list[FileChange]) -> tuple[int, int]:
    added = removed = 0
    for line in unified_diff(changes).splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


# --------------------------------------------------------------- apply / undo
def _state_dir(root: Path) -> Path:
    d = root / ".codebox"
    d.mkdir(exist_ok=True)
    gi = d / ".gitignore"
    if not gi.exists():
        gi.write_text("*\n", encoding="utf-8")
    return d


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".codebox.tmp")
    tmp.write_bytes(data)
    if path.exists():
        try:
            shutil.copymode(path, tmp)
        except OSError:
            pass
    os.replace(tmp, path)


def save_patch(root: Path, changes: list[FileChange]) -> Path:
    p = _state_dir(Path(root).resolve()) / "last_change.patch"
    p.write_text(unified_diff(changes), encoding="utf-8")
    return p


def apply_changes(root: Path, changes: list[FileChange]) -> Path:
    """Write the changes to disk (after backing up originals). Rolls back on failure."""
    base = Path(root).resolve()
    state = _state_dir(base)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    bdir = state / "backups" / stamp
    (bdir / "files").mkdir(parents=True)
    manifest: dict = {"files": [], "undone": False}
    for ch in changes:
        full = base / ch.path
        existed = full.exists()
        if existed:
            dest = bdir / "files" / ch.path
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(full, dest)
        manifest["files"].append(
            {"path": ch.path, "existed": existed, "sha256": hashlib.sha256(ch.encoded()).hexdigest()}
        )
    (bdir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    try:
        for ch in changes:
            _atomic_write(base / ch.path, ch.encoded())
    except Exception:
        _restore(base, bdir, manifest, check_hash=False)
        raise
    return bdir


def _restore(base: Path, bdir: Path, manifest: dict, check_hash: bool) -> tuple[list[str], list[str]]:
    restored: list[str] = []
    skipped: list[str] = []
    for entry in manifest["files"]:
        rel = entry["path"]
        full = base / rel
        if check_hash and full.exists():
            if hashlib.sha256(full.read_bytes()).hexdigest() != entry["sha256"]:
                skipped.append(rel)  # changed after Codebox wrote it - don't clobber
                continue
        if entry["existed"]:
            shutil.copy2(bdir / "files" / rel, full)
        elif full.exists():
            full.unlink()
            parent = full.parent
            while parent != base and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
        restored.append(rel)
    return restored, skipped


def undo_last(root: Path) -> tuple[list[str], list[str]] | None:
    """Undo the most recent applied change. Returns (restored, skipped) or None."""
    base = Path(root).resolve()
    backups = base / ".codebox" / "backups"
    if not backups.is_dir():
        return None
    for bdir in sorted(backups.iterdir(), reverse=True):
        mf = bdir / "manifest.json"
        if not mf.is_file():
            continue
        manifest = json.loads(mf.read_text(encoding="utf-8"))
        if manifest.get("undone"):
            continue
        restored, skipped = _restore(base, bdir, manifest, check_hash=True)
        manifest["undone"] = True
        mf.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return restored, skipped
    return None
