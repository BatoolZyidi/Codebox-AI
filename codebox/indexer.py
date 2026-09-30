"""Incremental symbol index of a repository (functions, classes, ...).

Python files are parsed with the standard `ast` module; other languages use
lightweight regular expressions. No native dependencies are needed.
"""
from __future__ import annotations

import ast
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from .safety import IGNORED_DIRS, is_sensitive


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str
    path: str
    line: int
    qual: str = ""


@dataclass
class FileInfo:
    path: str
    size: int
    mtime: float
    symbols: list[Symbol] = field(default_factory=list)


_JS = [
    ("function", r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)"),
    ("class", r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)"),
    ("function", r"^[ \t]*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*(?::[^=]+)?=>"),
    ("interface", r"^[ \t]*(?:export\s+)?interface\s+([A-Za-z_$][\w$]*)"),
    ("type", r"^[ \t]*(?:export\s+)?type\s+([A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\s*="),
]
_GO = [
    ("function", r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)"),
    ("type", r"^type\s+([A-Za-z_]\w*)\s+(?:struct|interface)"),
]
_RUST = [
    ("function", r"^[ \t]*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+([A-Za-z_]\w*)"),
    ("type", r"^[ \t]*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait)\s+([A-Za-z_]\w*)"),
]
_RUBY = [
    ("function", r"^[ \t]*def\s+(?:self\.)?([A-Za-z_]\w*[?!]?)"),
    ("class", r"^[ \t]*(?:class|module)\s+([A-Z]\w*)"),
]
_PHP = [
    ("function", r"^[ \t]*(?:(?:public|private|protected|static|final|abstract)\s+)*function\s+&?([A-Za-z_]\w*)"),
    ("class", r"^[ \t]*(?:abstract\s+|final\s+)?(?:class|interface|trait)\s+([A-Za-z_]\w*)"),
]
_JAVA_LIKE = [
    ("class", r"^[ \t]*(?:(?:public|private|protected|internal|static|final|abstract|sealed|partial|data)\s+)*(?:class|interface|enum|record|object|struct)\s+([A-Za-z_]\w*)"),
    ("function", r"^[ \t]*(?:(?:public|private|protected|internal|static|final|abstract|async|override|virtual|synchronized|suspend)\s+)+[\w<>\[\],.?]+\s+([A-Za-z_]\w*)\s*\("),
    ("function", r"^[ \t]*(?:(?:public|private|protected|internal|override|suspend)\s+)*fun\s+(?:<[^>]*>\s*)?(?:[\w.]+\.)?([A-Za-z_]\w*)\s*\("),
]
_C_LIKE = [
    ("class", r"^[ \t]*(?:class|struct)\s+([A-Za-z_]\w*)"),
    ("function", r"^[A-Za-z_][\w:<>\*&\s]*?\s+\**([A-Za-z_]\w*)\s*\([^;]*\)\s*(?:const\s*)?\{?\s*$"),
]
_GENERIC = [
    ("function", r"^[ \t]*(?:async\s+)?def\s+([A-Za-z_]\w*)"),
    ("class", r"^[ \t]*class\s+([A-Za-z_]\w*)"),
]

_EXT_GROUPS: dict[str, list[tuple[str, str]]] = {}
for _exts, _pats in (
    ((".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".vue", ".svelte"), _JS),
    ((".go",), _GO),
    ((".rs",), _RUST),
    ((".rb",), _RUBY),
    ((".php",), _PHP),
    ((".java", ".cs", ".kt", ".kts", ".scala", ".swift", ".dart"), _JAVA_LIKE),
    ((".c", ".h", ".cpp", ".cc", ".hpp", ".cxx"), _C_LIKE),
):
    for _e in _exts:
        _EXT_GROUPS[_e] = _pats
_COMPILED: dict[int, list[tuple[str, re.Pattern[str]]]] = {}


def _compiled(patterns: list[tuple[str, str]]) -> list[tuple[str, re.Pattern[str]]]:
    key = id(patterns)
    if key not in _COMPILED:
        _COMPILED[key] = [(k, re.compile(p, re.MULTILINE)) for k, p in patterns]
    return _COMPILED[key]


def _regex_symbols(path: str, text: str, patterns: list[tuple[str, str]]) -> list[Symbol]:
    out: list[Symbol] = []
    seen: set[tuple[str, int]] = set()
    for kind, rx in _compiled(patterns):
        for m in rx.finditer(text):
            name = m.group(1)
            line = text.count("\n", 0, m.start()) + 1
            if (name, line) in seen or name in {"if", "for", "while", "switch", "catch", "return"}:
                continue
            seen.add((name, line))
            out.append(Symbol(name, kind, path, line, name))
    out.sort(key=lambda s: s.line)
    return out


def _python_symbols(path: str, text: str) -> list[Symbol]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return _regex_symbols(path, text, _GENERIC)
    out: list[Symbol] = []

    def visit(body: list[ast.stmt], prefix: str, in_class: bool) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = "method" if in_class else "function"
                out.append(Symbol(node.name, kind, path, node.lineno, prefix + node.name))
                visit(node.body, prefix + node.name + ".", False)
            elif isinstance(node, ast.ClassDef):
                out.append(Symbol(node.name, "class", path, node.lineno, prefix + node.name))
                visit(node.body, prefix + node.name + ".", True)

    visit(tree.body, "", False)
    return out


def extract_symbols(path: str, text: str) -> list[Symbol]:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".py", ".pyi"):
        return _python_symbols(path, text)
    patterns = _EXT_GROUPS.get(ext)
    if patterns is None:
        return []
    return _regex_symbols(path, text, patterns)


def _load_gitignore(root: Path):  # type: ignore[no-untyped-def]
    gi = root / ".gitignore"
    if not gi.is_file():
        return None
    try:
        import pathspec

        lines = gi.read_text(encoding="utf-8", errors="ignore").splitlines()
        if hasattr(pathspec, "GitIgnoreSpec"):
            return pathspec.GitIgnoreSpec.from_lines(lines)
        return pathspec.PathSpec.from_lines("gitwildmatch", lines)
    except Exception:
        return None


class RepoIndex:
    def __init__(self, root: Path, max_file_bytes: int = 512_000, max_files: int = 20_000) -> None:
        self.root = Path(root).resolve()
        self.max_file_bytes = max_file_bytes
        self.max_files = max_files
        self.files: dict[str, FileInfo] = {}
        self._skipped: dict[str, tuple[float, int]] = {}

    # ------------------------------------------------------------------ scan
    def refresh(self) -> None:
        """Re-scan the folder, re-parsing only files that changed."""
        spec = _load_gitignore(self.root)
        seen: set[str] = set()
        for dirpath, dirnames, filenames in os.walk(self.root):
            rel_dir = os.path.relpath(dirpath, self.root).replace(os.sep, "/")
            rel_dir = "" if rel_dir == "." else rel_dir
            prefix = rel_dir + "/" if rel_dir else ""
            dirnames[:] = sorted(
                d for d in dirnames
                if d not in IGNORED_DIRS and not (spec and spec.match_file(prefix + d + "/"))
            )
            for name in sorted(filenames):
                rel = prefix + name
                if is_sensitive(name) or (spec and spec.match_file(rel)):
                    continue
                full = os.path.join(dirpath, name)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                if st.st_size == 0 or st.st_size > self.max_file_bytes:
                    continue
                sig = (st.st_mtime, st.st_size)
                known = self.files.get(rel)
                if known and (known.mtime, known.size) == sig:
                    seen.add(rel)
                    continue
                if self._skipped.get(rel) == sig:
                    continue
                try:
                    with open(full, "rb") as fh:
                        head = fh.read(4096)
                        if b"\x00" in head:
                            self._skipped[rel] = sig
                            continue
                        data = head + fh.read()
                    text = data.decode("utf-8", errors="replace")
                except OSError:
                    continue
                self.files[rel] = FileInfo(rel, st.st_size, st.st_mtime, extract_symbols(rel, text))
                seen.add(rel)
                if len(seen) >= self.max_files:
                    break
            if len(seen) >= self.max_files:
                break
        for gone in set(self.files) - seen:
            del self.files[gone]

    # --------------------------------------------------------------- queries
    def all_symbols(self) -> Iterator[Symbol]:
        for info in self.files.values():
            yield from info.symbols

    def read(self, rel: str) -> str | None:
        """File text with LF line endings, or None if unreadable."""
        try:
            data = (self.root / rel).read_bytes()
        except OSError:
            return None
        return data.decode("utf-8", errors="replace").replace("\r\n", "\n")

    def tree(self, limit: int = 150) -> list[str]:
        paths = sorted(self.files)
        if len(paths) <= limit:
            return paths
        groups: Counter[str] = Counter()
        for p in paths:
            parts = p.split("/")
            groups["/".join(parts[:2]) + "/" if len(parts) >= 3 else p] += 1
        out = []
        for key in sorted(groups):
            out.append(f"{key} ({groups[key]} files)" if key.endswith("/") else key)
        return out[:limit]
