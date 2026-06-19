"""Persist the code graph (graph.db, embeddings included) in an orphan service
branch of the repo, so PR reviews reuse it instead of rebuilding from scratch.

The branch holds a single ``graph.db`` and is force-pushed as one commit on
every rebuild, so it never accumulates history and ``main`` stays clean.
"""
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

_DB_REL = os.path.join(".code-review-graph", "graph.db")
_DB_NAME = "graph.db"  # name inside the cache branch


def _auth_url(token: str, owner: str, repo: str) -> str:
    return f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"


def _run(args: list[str], cwd: str | None, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, timeout=timeout)


def graph_db_path(repo_dir: str) -> str:
    """Absolute path of the graph DB inside a repo checkout."""
    return os.path.join(repo_dir, _DB_REL)


def restore_from_cache(repo_dir: str, token: str, owner: str, repo: str, branch: str) -> bool:
    """Fetch graph.db from the cache branch into repo_dir. Returns True on hit.

    A missing branch (first run) is a normal cache miss, not an error.
    """
    url = _auth_url(token, owner, repo)
    try:
        fetch = _run(["git", "fetch", "--depth", "1", url, branch], cwd=repo_dir)
        if fetch.returncode != 0:
            logger.info("No graph cache on '%s' (cache miss)", branch)
            return False
        show = _run(["git", "show", f"FETCH_HEAD:{_DB_NAME}"], cwd=repo_dir, timeout=60)
        if show.returncode != 0 or not show.stdout:
            logger.info("Cache branch '%s' has no %s", branch, _DB_NAME)
            return False
        target = Path(graph_db_path(repo_dir))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(show.stdout)
        logger.info("Restored graph cache (%d bytes) from '%s'", len(show.stdout), branch)
        return True
    except Exception as e:
        logger.warning("restore_from_cache failed: %s", e)
        return False


def save_to_cache(repo_dir: str, token: str, owner: str, repo: str, branch: str) -> bool:
    """Force-push repo_dir's graph.db as a single-commit orphan branch. True on success."""
    return save_to_remote(repo_dir, _auth_url(token, owner, repo), branch)


def save_to_remote(repo_dir: str, remote_url: str, branch: str) -> bool:
    """Force-push repo_dir's graph.db to ``remote_url`` as a single orphan commit.

    Used both by the push handler (token URL) and the bootstrap script (the
    repo's own ``origin`` URL). True on success.
    """
    db = graph_db_path(repo_dir)
    if not os.path.isfile(db):
        logger.warning("save_to_remote: no graph DB at %s", db)
        return False

    url = remote_url
    tmp = tempfile.mkdtemp(prefix="crg-cache-")
    try:
        init = _run(["git", "init", "-q"], cwd=tmp)
        if init.returncode != 0:
            logger.warning("cache git init failed: %s", init.stderr.decode(errors="replace"))
            return False
        shutil.copy2(db, os.path.join(tmp, _DB_NAME))
        _run(["git", "add", _DB_NAME], cwd=tmp)
        commit = _run(
            [
                "git",
                "-c", f"user.name={settings.git_author_name}",
                "-c", f"user.email={settings.git_author_email}",
                "commit", "-q", "-m", "chore(crg): update code graph cache",
            ],
            cwd=tmp,
        )
        if commit.returncode != 0:
            logger.warning("cache commit failed: %s", commit.stderr.decode(errors="replace"))
            return False
        push = _run(["git", "push", "-f", url, f"HEAD:{branch}"], cwd=tmp, timeout=180)
        if push.returncode != 0:
            logger.warning("cache push failed: %s", push.stderr.decode(errors="replace"))
            return False
        logger.info("Saved graph cache to '%s'", branch)
        return True
    except Exception as e:
        logger.warning("save_to_cache failed: %s", e)
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
