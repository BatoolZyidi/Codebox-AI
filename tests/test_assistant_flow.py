import asyncio
import json

from codebox.assistant import Assistant
from codebox.indexer import RepoIndex
from codebox.llm import parse_result
from tests.helpers import make_repo, make_settings


class FakeSpeaker:
    def __init__(self):
        self.said = []

    async def say(self, text):
        self.said.append(text)


class FakeLLM:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return self.replies.pop(0)


def build(tmp_path, *replies, **settings_kw):
    root = make_repo(tmp_path)
    idx = RepoIndex(root)
    idx.refresh()
    sp, llm = FakeSpeaker(), FakeLLM(*replies)
    return Assistant(make_settings(**settings_kw), idx, llm, sp), sp, llm, root


RENAME = json.dumps({
    "kind": "change", "spoken": "Renaming get user to fetch user",
    "edits": [
        {"path": "app/auth.py", "old": "get_user", "new": "fetch_user", "replace_all": True},
        {"path": "app/views.py", "old": "get_user", "new": "fetch_user", "replace_all": True},
    ],
})


def test_sleeping_ignores_everything_until_wake(tmp_path):
    async def go():
        a, sp, llm, _ = build(tmp_path)
        await a.handle("where is login handled")
        await a.handle("apply")
        assert sp.said == [] and llm.prompts == []
        await a.handle("Wake up, Codebox AI.")
        assert a.awake and "awake" in sp.said[-1].lower()
    asyncio.run(go())


def test_full_voice_session(tmp_path):
    async def go():
        answer = json.dumps({"kind": "answer", "spoken": "Login is handled in auth dot py.", "edits": []})
        a, sp, llm, root = build(tmp_path, answer, RENAME)
        await a.handle("wakeup codebox AI")
        await a.handle("where is login handled")
        assert sp.said[-1] == "Login is handled in auth dot py."
        assert "LoginService" in llm.prompts[0]  # relevant file sent as context
        assert ".env" not in llm.prompts[0] and "SECRET" not in llm.prompts[0]

        await a.handle("rename get user to fetch user everywhere")
        assert a.pending is not None
        assert "This will change 2 files" in sp.said[-1]
        assert "get_user" in (root / "app" / "auth.py").read_text()  # NOT applied yet

        await a.handle("read it again")
        assert sp.said[-1] == a.pending.summary
        await a.handle("something else entirely")  # must not start new request while pending
        assert "pending change" in sp.said[-1] and len(llm.prompts) == 2

        await a.handle("apply")
        assert a.pending is None and "Done" in sp.said[-1]
        assert "fetch_user" in (root / "app" / "auth.py").read_text()
        assert "fetch_user" in (root / "app" / "views.py").read_text()
        assert (root / ".codebox" / "last_change.patch").exists()

        await a.handle("undo")
        assert "Undone" in sp.said[-1]
        assert "get_user" in (root / "app" / "auth.py").read_text()

        await a.handle("close yourself codebox AI")
        assert not a.awake and "sleep" in sp.said[-1].lower()
        await a.handle("wake up codebox ai")
        assert a.awake
    asyncio.run(go())


def test_reject_leaves_files_alone(tmp_path):
    async def go():
        a, sp, _, root = build(tmp_path, RENAME)
        a.awake = True
        before = (root / "app" / "auth.py").read_text()
        await a.handle("rename get user to fetch user")
        await a.handle("reject")
        assert a.pending is None and (root / "app" / "auth.py").read_text() == before
        await a.handle("apply")
        assert sp.said[-1] == "There is no pending change."
    asyncio.run(go())


def test_wake_phrase_with_command_in_same_breath(tmp_path):
    async def go():
        answer = json.dumps({"kind": "answer", "spoken": "It is in views.", "edits": []})
        a, sp, llm, _ = build(tmp_path, answer)
        await a.handle("Wake up Codebox AI, where is the profile view?")
        assert sp.said == ["Awake.", "It is in views."]
        assert "where is the profile view?" in llm.prompts[0]
    asyncio.run(go())


def test_bad_edit_is_retried_then_succeeds(tmp_path):
    async def go():
        bad = json.dumps({"kind": "change", "spoken": "x", "edits": [{"path": "app/auth.py", "old": "does not exist", "new": "y"}]})
        a, sp, llm, _ = build(tmp_path, bad, RENAME)
        a.awake = True
        await a.handle("rename get user to fetch user")
        assert len(llm.prompts) == 2 and "REJECTED" in llm.prompts[1]
        assert a.pending is not None
    asyncio.run(go())


def test_persistently_bad_edit_changes_nothing(tmp_path):
    async def go():
        bad = json.dumps({"kind": "change", "spoken": "x", "edits": [{"path": ".env", "old": "", "new": "hack"}]})
        a, sp, _, root = build(tmp_path, bad, bad)
        a.awake = True
        await a.handle("do something")
        assert a.pending is None and "couldn't prepare a safe change" in sp.said[-1]
        assert (root / ".env").read_text() == "SECRET=1\n"
    asyncio.run(go())


def test_llm_failure_is_spoken_not_fatal(tmp_path):
    async def go():
        a, sp, llm, _ = build(tmp_path)
        a.awake = True
        await a.handle("where is login")  # FakeLLM has no replies -> IndexError inside thread
        assert "couldn't reach the AI service" in sp.said[-1]
        await a.handle("help")
        assert "apply" in sp.said[-1]
    asyncio.run(go())


def test_close_action_exit(tmp_path):
    async def go():
        a, sp, _, _ = build(tmp_path, close_action="exit")
        a.awake = True
        await a.handle("close yourself codebox AI")
        assert a.stop_event.is_set() and sp.said[-1] == "Goodbye."
    asyncio.run(go())


def test_parse_result_tolerates_fences_and_junk():
    r = parse_result('```json\n{"kind":"answer","spoken":"hi"}\n```')
    assert r.kind == "answer" and r.spoken == "hi"
    r = parse_result('Sure! {"spoken":"x","edits":[{"path":"a.py","old":"a","new":"b"}]} thanks')
    assert r.kind == "change" and r.edits[0].path == "a.py"
    for bad in ["", "not json", "[1,2]", '{"kind":"change","spoken":"x","edits":[]}']:
        try:
            parse_result(bad)
            assert False, bad
        except ValueError:
            pass
