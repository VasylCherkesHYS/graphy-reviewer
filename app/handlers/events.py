import logging

from app.config import settings
from app.github import client as gh
from app.github.auth import get_installation_token
from app.review import clone, graph, poster, reviewer

logger = logging.getLogger(__name__)

# Simple in-memory dedup: last 500 delivery IDs
_seen_deliveries: set[str] = set()
_seen_order: list[str] = []


def _is_duplicate(delivery_id: str) -> bool:
    if delivery_id in _seen_deliveries:
        return True
    _seen_deliveries.add(delivery_id)
    _seen_order.append(delivery_id)
    if len(_seen_order) > 500:
        old = _seen_order.pop(0)
        _seen_deliveries.discard(old)
    return False


async def handle_event(event: str, payload: dict, delivery_id: str) -> None:
    if _is_duplicate(delivery_id):
        logger.info("Duplicate delivery %s, skipping", delivery_id)
        return

    if event == "pull_request":
        action = payload.get("action", "")
        if action in ("opened", "synchronize", "reopened"):
            await _handle_pr_opened(payload)

    elif event == "pull_request_review_comment":
        action = payload.get("action", "")
        if action == "created":
            await _handle_review_comment(payload)


async def _handle_pr_opened(payload: dict) -> None:
    installation_id: int = payload["installation"]["id"]
    repo_data = payload["repository"]
    owner: str = repo_data["owner"]["login"]
    repo: str = repo_data["name"]
    pr = payload["pull_request"]
    pr_number: int = pr["number"]
    base_sha: str = pr["base"]["sha"]
    head_sha: str = pr["head"]["sha"]

    logger.info("PR review started: %s/%s#%d", owner, repo, pr_number)

    token = await get_installation_token(installation_id)

    diff = await gh.get_pr_diff(token, owner, repo, pr_number)

    # Clone repo and build graph
    tmp = None
    graph_context = "(граф коду недоступний — аналізуй тільки diff)"
    try:
        ref = f"refs/pull/{pr_number}/head"
        tmp = clone.clone_repo(token, owner, repo, ref, base_sha, depth=settings.clone_depth)
        if graph.ensure_graph(tmp):
            graph_context = graph.detect_changes(tmp, base_sha)
    except Exception as e:
        logger.warning("Graph step failed: %s", e)
    finally:
        if tmp:
            clone.cleanup(tmp)

    result = await reviewer.review_pr(diff, graph_context)
    await poster.post_review(token, owner, repo, pr_number, head_sha, result)
    logger.info("PR review done: %s/%s#%d findings=%d", owner, repo, pr_number, len(result.findings))


async def _handle_review_comment(payload: dict) -> None:
    comment = payload["comment"]
    sender = payload["sender"]

    # Skip bot replies to avoid infinite loops
    if sender.get("type") == "Bot" or "[bot]" in sender.get("login", ""):
        return

    # Only react to replies in a thread (not top-level comments)
    in_reply_to_id: int | None = comment.get("in_reply_to_id")
    if not in_reply_to_id:
        return

    installation_id: int = payload["installation"]["id"]
    repo_data = payload["repository"]
    owner: str = repo_data["owner"]["login"]
    repo: str = repo_data["name"]
    pr_number: int = payload["pull_request"]["number"]

    token = await get_installation_token(installation_id)

    # Fetch the original bot comment
    try:
        original = await gh.get_review_comment(token, owner, repo, in_reply_to_id)
    except Exception as e:
        logger.warning("Could not fetch parent comment %d: %s", in_reply_to_id, e)
        return

    # Only reply if the parent comment was posted by our bot
    if original.get("user", {}).get("type") != "Bot":
        return

    diff_hunk: str = comment.get("diff_hunk", "")
    file_path: str = comment.get("path", "")
    user_reply: str = comment.get("body", "")

    reply_text = await reviewer.reply_to_comment(
        original_comment=original["body"],
        diff_hunk=diff_hunk,
        file_path=file_path,
        user_reply=user_reply,
    )

    await gh.reply_to_review_comment(token, owner, repo, pr_number, comment["id"], reply_text)
    logger.info("Dialog reply posted on comment %d", comment["id"])
