"""One-shot bootstrap: build the code graph (+ OpenAI embeddings) for a repo
checkout and force-push it to the cache branch, so the very first PR review
already gets a cache hit instead of building from scratch.

In production this happens automatically on every push to the default branch
(see app.handlers.events._refresh_graph); this script just primes the cache once
from a local checkout, pushing via the checkout's own ``origin`` remote.

Usage:
    python -m scripts.bootstrap_graph [REPO_DIR]

Requirements:
    - `code-review-graph` installed (pip install -e .)
    - OPENAI_API_KEY set (in .env or the environment)
    - the checkout's `origin` points at the GitHub repo and you can push to it
"""
import subprocess
import sys

from app.config import settings
from app.review import graph, graph_cache


def _origin_url(repo_dir: str) -> str:
    out = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=repo_dir, capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def main(argv: list[str]) -> int:
    repo_dir = argv[1] if len(argv) > 1 else "."
    branch = settings.graph_cache_branch

    print(f"[1/3] Building graph in {repo_dir} ...")
    if not graph.ensure_graph(repo_dir):
        print("ERROR: graph build/update failed", file=sys.stderr)
        return 1

    print("[2/3] Building OpenAI embeddings ...")
    if not graph.build_embeddings(repo_dir):
        print(
            "WARNING: embeddings were not built (check OPENAI_API_KEY / node count). "
            "The graph will still be cached without vectors.",
            file=sys.stderr,
        )

    url = _origin_url(repo_dir)
    print(f"[3/3] Force-pushing graph.db to '{branch}' on {url} ...")
    if not graph_cache.save_to_remote(repo_dir, url, branch):
        print("ERROR: pushing the cache branch failed", file=sys.stderr)
        return 1

    print(f"Done. Graph cached on branch '{branch}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
