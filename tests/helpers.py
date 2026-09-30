from pathlib import Path

from codebox.config import Settings


def make_settings(**kw) -> Settings:
    base = dict(
        assemblyai_api_key="test", gemini_api_key="test", tts_enabled=False,
        echo_tail_seconds=0.0, _env_file=None,
    )
    base.update(kw)
    return Settings(**base)


def make_repo(tmp: Path) -> Path:
    (tmp / "app").mkdir()
    (tmp / "app" / "auth.py").write_text(
        "def get_user(user_id):\n    return {'id': user_id}\n\n\nclass LoginService:\n"
        "    def login(self, name):\n        user = get_user(name)\n        return user\n"
    )
    (tmp / "app" / "views.py").write_text(
        "from app.auth import get_user\n\n\ndef profile(uid):\n    return get_user(uid)\n"
    )
    (tmp / "web.js").write_text(
        "export function renderPage(x) { return x }\nconst loadData = async (id) => id\n"
        "export class PageStore {}\n"
    )
    (tmp / ".env").write_text("SECRET=1\n")
    (tmp / "node_modules").mkdir()
    (tmp / "node_modules" / "junk.js").write_text("function junk() {}\n")
    (tmp / ".gitignore").write_text("ignored_dir/\n*.log\n")
    (tmp / "ignored_dir").mkdir()
    (tmp / "ignored_dir" / "x.py").write_text("def hidden(): pass\n")
    (tmp / "debug.log").write_text("hello\n")
    (tmp / "crlf.txt").write_bytes(b"line one\r\nline two\r\n")
    return tmp
