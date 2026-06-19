import types
from pathlib import Path

from app.review import graph_cache


def _cp(returncode=0, stdout=b"", stderr=b""):
    return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_restore_cache_miss(monkeypatch, tmp_path):
    def fake_run(args, **k):
        if "fetch" in args:
            return _cp(returncode=1, stderr=b"couldn't find remote ref")
        raise AssertionError("show should not run on a cache miss")

    monkeypatch.setattr(graph_cache.subprocess, "run", fake_run)
    assert graph_cache.restore_from_cache(str(tmp_path), "tok", "o", "r", "crg-cache") is False


def test_restore_cache_hit_writes_db(monkeypatch, tmp_path):
    def fake_run(args, **k):
        if "fetch" in args:
            return _cp(returncode=0)
        if "show" in args:
            return _cp(returncode=0, stdout=b"SQLITEDATA")
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr(graph_cache.subprocess, "run", fake_run)
    ok = graph_cache.restore_from_cache(str(tmp_path), "tok", "o", "r", "crg-cache")
    assert ok is True
    db = Path(graph_cache.graph_db_path(str(tmp_path)))
    assert db.read_bytes() == b"SQLITEDATA"


def test_save_to_remote_no_db(tmp_path):
    assert graph_cache.save_to_remote(str(tmp_path), "https://example/x.git", "crg-cache") is False


def test_save_to_remote_pushes(monkeypatch, tmp_path):
    db = Path(graph_cache.graph_db_path(str(tmp_path)))
    db.parent.mkdir(parents=True)
    db.write_bytes(b"SQLITEDATA")

    calls = []

    def fake_run(args, **k):
        calls.append(args)
        return _cp(returncode=0)

    monkeypatch.setattr(graph_cache.subprocess, "run", fake_run)
    ok = graph_cache.save_to_remote(str(tmp_path), "https://example/x.git", "crg-cache")
    assert ok is True

    push = next(a for a in calls if "push" in a)
    assert "-f" in push
    assert "HEAD:crg-cache" in push
    assert "https://example/x.git" in push


def test_save_to_remote_push_failure(monkeypatch, tmp_path):
    db = Path(graph_cache.graph_db_path(str(tmp_path)))
    db.parent.mkdir(parents=True)
    db.write_bytes(b"DATA")

    def fake_run(args, **k):
        if "push" in args:
            return _cp(returncode=1, stderr=b"denied")
        return _cp(returncode=0)

    monkeypatch.setattr(graph_cache.subprocess, "run", fake_run)
    assert graph_cache.save_to_remote(str(tmp_path), "https://example/x.git", "crg-cache") is False
