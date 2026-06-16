import logging
import shutil
import subprocess
import tempfile

logger = logging.getLogger(__name__)


def clone_repo(token: str, owner: str, repo: str, ref: str, base_sha: str, depth: int = 100) -> str:
    """Clone repo to a temp dir and ensure base_sha is in history. Returns tmp path."""
    tmp = tempfile.mkdtemp(prefix="ai-review-")
    url = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
    try:
        subprocess.run(
            ["git", "clone", "--depth", str(depth), url, tmp],
            check=True, capture_output=True, timeout=120,
        )
        # fetch the base sha explicitly in case it's outside shallow depth
        subprocess.run(
            ["git", "fetch", "--depth", str(depth), "origin", base_sha],
            cwd=tmp, capture_output=True, timeout=60,
        )
        # checkout the head ref (merge commit or branch head)
        subprocess.run(
            ["git", "fetch", "--depth", str(depth), "origin", ref],
            cwd=tmp, capture_output=True, timeout=60,
        )
        subprocess.run(
            ["git", "checkout", "FETCH_HEAD"],
            cwd=tmp, capture_output=True, timeout=30,
        )
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return tmp


def cleanup(tmp: str) -> None:
    shutil.rmtree(tmp, ignore_errors=True)
