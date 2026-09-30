"""Forgiving matching of the wake / close phrases in speech-recognition text."""
from __future__ import annotations

import difflib
import re


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


class PhraseMatcher:
    """Matches a spoken phrase however the recogniser spaces or punctuates it.

    "wakeup codebox AI" also matches "Wake up, code box A.I." Returns whatever
    was said after the phrase so "wakeup codebox AI where is login" works.
    """

    def __init__(self, phrase: str, fuzzy: float = 0.86) -> None:
        self.phrase = phrase
        self.key = _norm(phrase)
        if not self.key:
            raise ValueError("phrase must contain letters or digits")
        self._re = re.compile(r"[\W_]*".join(re.escape(c) for c in self.key), re.IGNORECASE)
        self._fuzzy = fuzzy

    def find(self, text: str) -> tuple[bool, str]:
        m = self._re.search(text)
        if m:
            return True, text[m.end():].lstrip(" ,.!?;:-").strip()
        t = _norm(text)
        n = len(self.key)
        if len(t) < n - 2:
            return False, ""
        for size in (n - 1, n, n + 1):
            for i in range(0, max(1, len(t) - size + 1)):
                window = t[i:i + size]
                if difflib.SequenceMatcher(None, window, self.key).ratio() >= self._fuzzy:
                    return True, ""
        return False, ""
