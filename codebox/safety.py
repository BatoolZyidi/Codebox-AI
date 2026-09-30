"""Path and file safety rules shared by the indexer and the edit engine."""
from __future__ import annotations

# Directories that are never indexed.
IGNORED_DIRS = frozenset(
    {
        ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "env",
        ".idea", ".vscode", "dist", "build", ".next", ".nuxt", ".cache", "target",
        ".codebox", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", "coverage",
        ".gradle", ".terraform",
    }
)

# Directories Codebox will refuse to write into.
PROTECTED_DIRS = frozenset(
    {".git", ".hg", ".svn", ".codebox", "node_modules", ".venv", "venv", "__pycache__"}
)

_ENV_SAFE = frozenset({".env.example", ".env.sample", ".env.template"})
_SENSITIVE_NAMES = frozenset(
    {
        "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "credentials", "credentials.json",
        "secrets.json", "secrets.yml", "secrets.yaml", ".npmrc", ".pypirc", ".netrc",
        "service-account.json",
    }
)
_SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore", ".jks")


def is_sensitive(name: str) -> bool:
    """True for files that may hold secrets. These are never read, sent to the LLM, or edited."""
    n = name.lower()
    if n in _ENV_SAFE:
        return False
    if n == ".env" or n.startswith(".env."):
        return True
    if n in _SENSITIVE_NAMES:
        return True
    return n.endswith(_SENSITIVE_SUFFIXES)
