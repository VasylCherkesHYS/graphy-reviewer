import logging
import os
import sqlite3
import subprocess
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

FALLBACK = "(code graph unavailable — analyze the diff only)"
FALLBACK_SEMANTIC = "(semantic context unavailable — analyze the diff only)"

_SNIPPET_MAX_LINES = 40  # cap per related symbol so one big function can't eat the budget


def _db_path(repo_dir: str) -> Path:
    """Default location of the graph DB inside a repo checkout."""
    return Path(repo_dir) / ".code-review-graph" / "graph.db"


def ensure_graph(repo_dir: str) -> bool:
    """Build or update the code graph. Returns True on success.

    Runs an incremental ``update`` first (cheap when a graph DB was restored
    from the cache branch); falls back to a full ``build`` when there is no
    existing graph to update.
    """
    try:
        result = subprocess.run(
            ["code-review-graph", "update"],
            cwd=repo_dir,
            capture_output=True,
            timeout=settings.graph_timeout,
        )
        if result.returncode != 0:
            subprocess.run(
                ["code-review-graph", "build"],
                cwd=repo_dir,
                capture_output=True,
                timeout=settings.graph_timeout,
                check=True,
            )
        return True
    except Exception as e:
        logger.warning("code-review-graph build/update failed: %s", e)
        return False


def detect_changes(repo_dir: str, base_sha: str) -> str:
    """Run detect-changes --base <sha> --brief. Returns text or fallback."""
    try:
        result = subprocess.run(
            ["code-review-graph", "detect-changes", "--base", base_sha, "--brief"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=settings.graph_timeout,
        )
        output = result.stdout.strip()
        return output if output else FALLBACK
    except Exception as e:
        logger.warning("code-review-graph detect-changes failed: %s", e)
        return FALLBACK


# --------------------------------------------------------------------------- #
# Vector embeddings (semantic context)
# --------------------------------------------------------------------------- #

def _ensure_embedding_env() -> None:
    """Export the CRG_* env vars the OpenAI embedding provider reads.

    Both the ``embed`` subprocess and the in-process semantic-search call pick
    these up. Derived from the app's existing OpenAI settings so we don't need a
    second key. Idempotent.
    """
    os.environ["CRG_OPENAI_API_KEY"] = settings.openai_api_key
    os.environ["CRG_OPENAI_BASE_URL"] = settings.openai_embedding_base_url
    os.environ["CRG_OPENAI_MODEL"] = settings.openai_embedding_model
    # Acknowledge cloud egress once so the provider doesn't print a warning.
    os.environ.setdefault("CRG_ACCEPT_CLOUD_EMBEDDINGS", "1")


def _node_count(repo_dir: str) -> int | None:
    """Number of nodes in the graph DB, or None if it can't be read."""
    db = _db_path(repo_dir)
    if not db.exists():
        return None
    try:
        con = sqlite3.connect(str(db))
        try:
            (count,) = con.execute("SELECT COUNT(*) FROM nodes").fetchone()
            return int(count)
        finally:
            con.close()
    except Exception as e:
        logger.warning("Could not read node count: %s", e)
        return None


def build_embeddings(repo_dir: str) -> bool:
    """Compute OpenAI vector embeddings for the graph. Returns True on success.

    Only nodes whose text changed are re-embedded (cheap on the PR path after a
    cached graph is restored). Skipped when semantic context is disabled, no
    OpenAI key is set, or the graph exceeds ``max_embed_nodes`` (cost guard).
    """
    if not settings.enable_semantic_context:
        return False
    if not settings.openai_api_key:
        logger.info("No OPENAI_API_KEY set — skipping embeddings")
        return False

    nodes = _node_count(repo_dir)
    if nodes is not None and nodes > settings.max_embed_nodes:
        logger.warning(
            "Skipping embeddings: %d nodes > max_embed_nodes=%d",
            nodes,
            settings.max_embed_nodes,
        )
        return False

    _ensure_embedding_env()
    try:
        result = subprocess.run(
            [
                "code-review-graph", "embed",
                "--provider", "openai",
                "--model", settings.openai_embedding_model,
            ],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=settings.embed_timeout,
        )
        if result.returncode != 0:
            logger.warning("code-review-graph embed failed: %s", result.stderr.strip())
            return False
        logger.info("Embeddings built: %s", result.stdout.strip())
        return True
    except Exception as e:
        logger.warning("build_embeddings failed: %s", e)
        return False


def _changed_files(diff: str) -> list[str]:
    """Paths of files touched by a unified diff (from the ``+++ b/`` headers)."""
    files = []
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            path = line[len("+++ b/"):].strip()
            if path and path != "/dev/null":
                files.append(path)
    return files


def _query_from_diff(diff: str, max_chars: int = 2_000) -> str:
    """Build a semantic-search query from the diff: changed filenames + added code."""
    basenames = [f.rsplit("/", 1)[-1] for f in _changed_files(diff)]
    added = [
        line[1:]
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    query = " ".join(basenames) + "\n" + "\n".join(added)
    return query[:max_chars].strip()


def _read_snippet(repo_dir: str, file_path: str, start: int | None, end: int | None) -> str:
    """Read lines [start..end] (1-based) of a file in the clone; '' on any failure."""
    if not start:
        return ""
    full = os.path.normpath(os.path.join(repo_dir, file_path))
    if not full.startswith(os.path.normpath(repo_dir)) or not os.path.isfile(full):
        return ""
    last = end or start
    last = min(last, start + _SNIPPET_MAX_LINES - 1)
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except Exception:
        return ""
    return "\n".join(lines[start - 1:last])


def _render_related(repo_dir: str, results: list[dict]) -> str:
    """Render related symbols (with code snippets) into a budget-capped block."""
    blocks: list[str] = []
    used = 0
    for r in results:
        path = r.get("file_path") or "?"
        loc = f"{path}:{r['line_start']}" if r.get("line_start") else path
        header = f"--- {r.get('kind', '')} {r.get('name', '?')} @ {loc} ---".strip()
        snippet = _read_snippet(repo_dir, path, r.get("line_start"), r.get("line_end"))
        block = header + ("\n" + snippet if snippet else "")
        if used + len(block) + 2 > settings.max_related_chars:
            break
        blocks.append(block)
        used += len(block) + 2
    return "\n\n".join(blocks)


def semantic_context(repo_dir: str, diff: str) -> str:
    """Vector-search the graph for code related to the diff. Returns a prompt block.

    Returns FALLBACK_SEMANTIC when semantic context is disabled/unavailable or
    nothing relevant is found. Never raises.
    """
    if not settings.enable_semantic_context or not settings.openai_api_key:
        return FALLBACK_SEMANTIC

    query = _query_from_diff(diff)
    if not query:
        return FALLBACK_SEMANTIC

    _ensure_embedding_env()
    try:
        from code_review_graph.tools.query import semantic_search_nodes

        res = semantic_search_nodes(
            query=query,
            repo_root=repo_dir,
            limit=settings.semantic_top_k,
            provider="openai",
            model=settings.openai_embedding_model,
        )
    except Exception as e:
        logger.warning("semantic search failed: %s", e)
        return FALLBACK_SEMANTIC

    if not isinstance(res, dict) or res.get("status") != "ok":
        return FALLBACK_SEMANTIC

    changed = set(_changed_files(diff))
    related = [r for r in res.get("results", []) if r.get("file_path") not in changed]
    rendered = _render_related(repo_dir, related)
    return rendered or FALLBACK_SEMANTIC
