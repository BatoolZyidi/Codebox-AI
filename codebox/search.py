"""Whole-repository retrieval: symbol names + file paths + file contents.

Voice requests usually name things ("rename get user to fetch user"), so exact
and spoken-form matching works better than a vector database, needs no cloud
service, and never uploads the repository anywhere.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from .indexer import RepoIndex, Symbol

_STOP = frozenset(
    """a an the to of in on for and or is are was were be been me my it its this that these those
    please can could would should will you your i we us with from into by at as about all every
    everywhere there here now then so just some any what where which who how do does did
    show tell find explain change rename add update make write create remove delete fix
    look need want like function class file files code folder repository repo project method""".split()
)
_CAMEL_1 = re.compile(r"([a-z0-9])([A-Z])")
_CAMEL_2 = re.compile(r"([A-Z]+)([A-Z][a-z])")


def split_identifier(name: str) -> list[str]:
    """getUserByID -> ['get', 'user', 'by', 'id'];  fetch_user -> ['fetch', 'user']"""
    s = _CAMEL_2.sub(r"\1 \2", _CAMEL_1.sub(r"\1 \2", name))
    return [p for p in re.split(r"[^A-Za-z0-9]+", s.lower()) if p]


def request_terms(text: str) -> tuple[list[str], set[str]]:
    """Return (tokens, candidate_keys). Keys include joined n-grams, so the
    spoken words "get user" can match the identifier getUser."""
    tokens: list[str] = []
    keys: set[str] = set()
    for word in re.findall(r"[A-Za-z0-9_]+", text):
        parts = split_identifier(word)
        if len(parts) > 1:
            keys.add(word.lower().replace("_", ""))
        tokens.extend(parts)
    tokens = [t for t in tokens if t not in _STOP and len(t) > 1]
    keys.update(tokens)
    for n in (2, 3):
        for i in range(len(tokens) - n + 1):
            keys.add("".join(tokens[i:i + n]))
    return tokens, keys


@dataclass
class Hit:
    path: str
    score: float
    lines: list[int] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)


def retrieve(
    index: RepoIndex,
    request: str,
    boost_paths: Iterable[str] = (),
    limit: int = 8,
) -> list[Hit]:
    tokens, keys = request_terms(request)
    tokset = set(tokens)
    boost = set(boost_paths)
    hits: list[Hit] = []

    for path, info in index.files.items():
        score = 0.0
        lines: set[int] = set()
        matched: list[Symbol] = []

        for sym in info.symbols:
            key = sym.name.lower().replace("_", "")
            toks = {t for t in split_identifier(sym.name) if len(t) > 1}
            s = 0.0
            if key in keys:
                s = 10.0
            elif toks and toks <= tokset and len(toks) > 1:
                s = 6.0
            elif len(toks) > 1 and (toks & tokset):
                s = 1.5 * len(toks & tokset) / len(toks)
            if s:
                score += s
                lines.add(sym.line)
                if s >= 1.5:
                    matched.append(sym)

        path_l = path.lower()
        path_toks = set(split_identifier(path))
        for t in tokset:
            if t in path_toks:
                score += 3.0
            elif len(t) >= 4 and t in path_l:
                score += 1.5

        content_terms = [t for t in tokset if len(t) >= 3]
        if content_terms:
            text = index.read(path)
            if text is not None:
                low = text.lower()
                for t in content_terms:
                    c = low.count(t)
                    if c:
                        score += min(c, 5) * 0.4
                for n, line in enumerate(low.split("\n"), 1):
                    if n > 3000 or len(lines) > 40:
                        break
                    if any(t in line for t in content_terms):
                        lines.add(n)

        if path in boost:
            score += 2.0
        if score >= 1.0:
            hits.append(Hit(path, score, sorted(lines), matched))

    hits.sort(key=lambda h: (-h.score, h.path))
    hits = hits[:limit]
    if not hits:
        hits = _default_files(index, limit=3)
    return hits


_DEFAULT_NAMES = (
    "readme.md", "readme", "main.py", "app.py", "index.js", "index.ts", "main.go",
    "package.json", "pyproject.toml", "cargo.toml", "pom.xml",
)


def _default_files(index: RepoIndex, limit: int) -> list[Hit]:
    by_lower = {p.lower(): p for p in index.files}
    out = [Hit(by_lower[n], 0.0) for n in _DEFAULT_NAMES if n in by_lower]
    return out[:limit]


def _spoken(name: str) -> str:
    return " ".join(split_identifier(name))


def build_keyterms(index: RepoIndex, extra: Iterable[str] = (), limit: int = 80) -> list[str]:
    """Words to bias speech recognition toward: our commands + spoken symbol names."""
    seen: set[str] = set()
    terms: list[str] = []

    def add(term: str) -> None:
        t = term.strip()
        if 3 <= len(t) <= 40 and t.lower() not in seen:
            seen.add(t.lower())
            terms.append(t)

    for e in extra:
        add(e)
    syms = sorted(index.all_symbols(), key=lambda s: (s.kind != "class", s.name.lower()))
    for s in syms:
        if len(terms) >= limit:
            break
        add(_spoken(s.name))
    return terms[:limit]
