from codebox.indexer import RepoIndex
from codebox.search import build_keyterms, request_terms, retrieve, split_identifier
from tests.helpers import make_repo


def test_split_identifier():
    assert split_identifier("getUserByID") == ["get", "user", "by", "id"]
    assert split_identifier("fetch_user") == ["fetch", "user"]


def test_index_respects_ignores(tmp_path):
    idx = RepoIndex(make_repo(tmp_path))
    idx.refresh()
    files = set(idx.files)
    assert "app/auth.py" in files and "web.js" in files
    assert ".env" not in files
    assert not any(f.startswith(("node_modules", "ignored_dir")) for f in files)
    assert "debug.log" not in files


def test_symbols_python_and_js(tmp_path):
    idx = RepoIndex(make_repo(tmp_path))
    idx.refresh()
    names = {(s.name, s.kind) for s in idx.all_symbols()}
    assert ("get_user", "function") in names
    assert ("LoginService", "class") in names
    assert ("login", "method") in names
    assert ("renderPage", "function") in names
    assert ("loadData", "function") in names
    assert ("PageStore", "class") in names


def test_incremental_refresh(tmp_path):
    root = make_repo(tmp_path)
    idx = RepoIndex(root)
    idx.refresh()
    (root / "app" / "new.py").write_text("def brand_new(): pass\n")
    (root / "web.js").unlink()
    idx.refresh()
    assert "app/new.py" in idx.files and "web.js" not in idx.files


def test_spoken_words_find_identifier(tmp_path):
    idx = RepoIndex(make_repo(tmp_path))
    idx.refresh()
    _, keys = request_terms("rename get user to fetch user everywhere")
    assert "getuser" in keys
    hits = retrieve(idx, "rename get user to fetch user everywhere")
    assert hits[0].path == "app/auth.py"
    assert "app/views.py" in [h.path for h in hits]


def test_path_query_and_fallback(tmp_path):
    idx = RepoIndex(make_repo(tmp_path))
    idx.refresh()
    assert retrieve(idx, "explain the views")[0].path == "app/views.py"
    assert isinstance(retrieve(idx, "zzzz qqqq"), list)  # no crash on no match


def test_keyterms(tmp_path):
    idx = RepoIndex(make_repo(tmp_path))
    idx.refresh()
    terms = build_keyterms(idx, ["Codebox AI"])
    assert terms[0] == "Codebox AI" and "login service" in terms
    assert all(3 <= len(t) <= 40 for t in terms)
