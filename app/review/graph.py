import logging
import subprocess

from app.config import settings

logger = logging.getLogger(__name__)

FALLBACK = "(code graph unavailable — analyze the diff only)"


def ensure_graph(repo_dir: str) -> bool:
    """Build or update the code graph. Returns True on success."""
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
