import types

from app.review import graph

_DIFF = """\
diff --git a/app/foo.py b/app/foo.py
index 111..222 100644
--- a/app/foo.py
+++ b/app/foo.py
@@ -1,3 +1,4 @@
 import os
+def added():
+    return validate(x)
-old_line
"""


def test_changed_files():
    assert graph._changed_files(_DIFF) == ["app/foo.py"]


def test_changed_files_ignores_dev_null():
    diff = "--- a/x\n+++ /dev/null\n"
    assert graph._changed_files(diff) == []


def test_query_from_diff_has_basename_and_added_code():
    q = graph._query_from_diff(_DIFF)
    assert "foo.py" in q
    assert "def added():" in q
    assert "old_line" not in q  # removed lines excluded


def test_query_from_diff_truncates():
    big = "+++ b/a.py\n" + "\n".join("+" + "x" * 100 for _ in range(100))
    assert len(graph._query_from_diff(big, max_chars=200)) <= 200


def test_read_snippet(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("l1\nl2\nl3\nl4\n", encoding="utf-8")
    assert graph._read_snippet(str(tmp_path), "m.py", 2, 3) == "l2\nl3"


def test_read_snippet_path_traversal_blocked(tmp_path):
    assert graph._read_snippet(str(tmp_path), "../../etc/passwd", 1, 1) == ""


def test_read_snippet_missing_file(tmp_path):
    assert graph._read_snippet(str(tmp_path), "nope.py", 1, 1) == ""


def test_render_related_caps_budget(tmp_path, monkeypatch):
    f = tmp_path / "m.py"
    f.write_text("\n".join(f"line{i}" for i in range(50)), encoding="utf-8")
    monkeypatch.setattr(graph.settings, "max_related_chars", 60)
    results = [
        {"name": "a", "kind": "Function", "file_path": "m.py", "line_start": 1, "line_end": 3},
        {"name": "b", "kind": "Function", "file_path": "m.py", "line_start": 4, "line_end": 6},
        {"name": "c", "kind": "Function", "file_path": "m.py", "line_start": 7, "line_end": 9},
    ]
    out = graph._render_related(str(tmp_path), results)
    assert len(out) <= 120  # at least one block dropped by the cap
    assert "a @ m.py:1" in out


def test_semantic_context_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(graph.settings, "enable_semantic_context", False)
    assert graph.semantic_context(str(tmp_path), _DIFF) == graph.FALLBACK_SEMANTIC


def test_semantic_context_no_key(monkeypatch, tmp_path):
    monkeypatch.setattr(graph.settings, "openai_api_key", "")
    assert graph.semantic_context(str(tmp_path), _DIFF) == graph.FALLBACK_SEMANTIC


def test_semantic_context_success(monkeypatch, tmp_path):
    f = tmp_path / "app" / "bar.py"
    f.parent.mkdir(parents=True)
    f.write_text("def related():\n    return 1\n", encoding="utf-8")

    fake = types.ModuleType("code_review_graph.tools.query")
    fake.semantic_search_nodes = lambda **kw: {
        "status": "ok",
        "results": [
            {"name": "related", "kind": "Function", "file_path": "app/bar.py",
             "line_start": 1, "line_end": 2},
            # this one is in a changed file -> must be filtered out
            {"name": "added", "kind": "Function", "file_path": "app/foo.py",
             "line_start": 1, "line_end": 1},
        ],
    }
    _install_fake_query_module(monkeypatch, fake)

    out = graph.semantic_context(str(tmp_path), _DIFF)
    assert "related @ app/bar.py:1" in out
    assert "def related():" in out
    assert "app/foo.py" not in out  # changed file filtered


def test_semantic_context_handles_bad_result(monkeypatch, tmp_path):
    fake = types.ModuleType("code_review_graph.tools.query")
    fake.semantic_search_nodes = lambda **kw: {"status": "error", "error": "boom"}
    _install_fake_query_module(monkeypatch, fake)
    assert graph.semantic_context(str(tmp_path), _DIFF) == graph.FALLBACK_SEMANTIC


def _install_fake_query_module(monkeypatch, fake_query):
    """Make `from code_review_graph.tools.query import semantic_search_nodes` resolve."""
    import sys

    crg = types.ModuleType("code_review_graph")
    tools = types.ModuleType("code_review_graph.tools")
    tools.query = fake_query
    crg.tools = tools
    monkeypatch.setitem(sys.modules, "code_review_graph", crg)
    monkeypatch.setitem(sys.modules, "code_review_graph.tools", tools)
    monkeypatch.setitem(sys.modules, "code_review_graph.tools.query", fake_query)


def test_build_embeddings_no_key(monkeypatch, tmp_path):
    monkeypatch.setattr(graph.settings, "openai_api_key", "")
    assert graph.build_embeddings(str(tmp_path)) is False


def test_build_embeddings_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(graph.settings, "enable_semantic_context", False)
    assert graph.build_embeddings(str(tmp_path)) is False


def test_build_embeddings_node_guard(monkeypatch, tmp_path):
    monkeypatch.setattr(graph.settings, "max_embed_nodes", 100)
    monkeypatch.setattr(graph, "_node_count", lambda d: 500)
    called = []
    monkeypatch.setattr(graph.subprocess, "run", lambda *a, **k: called.append(a))
    assert graph.build_embeddings(str(tmp_path)) is False
    assert not called  # never reached the subprocess


def test_build_embeddings_success(monkeypatch, tmp_path):
    monkeypatch.setattr(graph, "_node_count", lambda d: 10)

    def fake_run(*a, **k):
        return types.SimpleNamespace(returncode=0, stdout="Embedded 10 nodes", stderr="")

    monkeypatch.setattr(graph.subprocess, "run", fake_run)
    assert graph.build_embeddings(str(tmp_path)) is True


def test_build_embeddings_subprocess_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(graph, "_node_count", lambda d: 10)

    def fake_run(*a, **k):
        return types.SimpleNamespace(returncode=1, stdout="", stderr="bad")

    monkeypatch.setattr(graph.subprocess, "run", fake_run)
    assert graph.build_embeddings(str(tmp_path)) is False
