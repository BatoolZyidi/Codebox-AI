import pytest

from codebox.edits import Edit, EditError, apply_changes, plan_changes, undo_last, unified_diff
from codebox.summary import details, summarize
from tests.helpers import make_repo


def test_plan_and_diff(tmp_path):
    root = make_repo(tmp_path)
    ch = plan_changes(root, [Edit("app/auth.py", "get_user", "fetch_user", replace_all=True)])
    assert ch[0].places == 2 and "fetch_user" in ch[0].after
    d = unified_diff(ch)
    assert "--- a/app/auth.py" in d and "+++ b/app/auth.py" in d
    # dry run must not touch disk
    assert "fetch_user" not in (root / "app" / "auth.py").read_text()


def test_ambiguous_and_missing_text_rejected(tmp_path):
    root = make_repo(tmp_path)
    with pytest.raises(EditError, match="appears 2 times"):
        plan_changes(root, [Edit("app/auth.py", "get_user", "x")])
    with pytest.raises(EditError, match="not found"):
        plan_changes(root, [Edit("app/auth.py", "nope_nope", "x")])
    with pytest.raises(EditError, match="does not exist"):
        plan_changes(root, [Edit("app/ghost.py", "a", "b")])


@pytest.mark.parametrize("bad", ["../outside.py", "/etc/passwd", ".env", ".git/config", "node_modules/x.js", "C:/x.py", ""])
def test_unsafe_paths_rejected(tmp_path, bad):
    root = make_repo(tmp_path)
    with pytest.raises(EditError):
        plan_changes(root, [Edit(bad, "", "x")])


def test_cannot_overwrite_existing_via_empty_old(tmp_path):
    root = make_repo(tmp_path)
    with pytest.raises(EditError, match="already exists"):
        plan_changes(root, [Edit("app/auth.py", "", "boom")])


def test_noop_rejected(tmp_path):
    root = make_repo(tmp_path)
    with pytest.raises(EditError, match="not change anything"):
        plan_changes(root, [Edit("app/auth.py", "get_user(user_id)", "get_user(user_id)")])


def test_apply_and_undo_including_new_file_and_crlf(tmp_path):
    root = make_repo(tmp_path)
    original = (root / "app" / "views.py").read_bytes()
    ch = plan_changes(root, [
        Edit("app/views.py", "def profile(uid):", "def profile_page(uid):"),
        Edit("crlf.txt", "line two", "line 2"),
        Edit("app/helpers/new.py", "", "def helper():\n    return 1\n"),
    ])
    apply_changes(root, ch)
    assert "profile_page" in (root / "app" / "views.py").read_text()
    assert (root / "crlf.txt").read_bytes() == b"line one\r\nline 2\r\n"  # CRLF preserved
    assert (root / "app" / "helpers" / "new.py").exists()

    restored, skipped = undo_last(root)
    assert not skipped and len(restored) == 3
    assert (root / "app" / "views.py").read_bytes() == original
    assert not (root / "app" / "helpers" / "new.py").exists()
    assert not (root / "app" / "helpers").exists()  # empty folder cleaned up
    assert undo_last(root) is None  # already undone


def test_undo_skips_files_changed_since(tmp_path):
    root = make_repo(tmp_path)
    apply_changes(root, plan_changes(root, [Edit("app/views.py", "profile", "profile2")]))
    (root / "app" / "views.py").write_text("user edited this\n")
    restored, skipped = undo_last(root)
    assert skipped == ["app/views.py"]
    assert (root / "app" / "views.py").read_text() == "user edited this\n"


def test_summary_text(tmp_path):
    root = make_repo(tmp_path)
    ch = plan_changes(root, [
        Edit("app/auth.py", "get_user", "fetch_user", replace_all=True),
        Edit("app/new.py", "", "x = 1\n"),
    ])
    s = summarize(ch, "Renaming get user to fetch user")
    assert "auth.py in 2 places" in s and "create new.py" in s.replace("It will create ", "create ")
    assert s.endswith("Say apply, reject, details, or read it again.")
    assert "auth.py" in details(ch)
