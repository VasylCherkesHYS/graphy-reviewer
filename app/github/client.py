import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE = "https://api.github.com"
HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
_REACTIONS_ACCEPT = "application/vnd.github.squirrel-girl-preview+json"
_DEFAULT_TIMEOUT = 30


def _auth(token: str) -> dict:
    return {**HEADERS, "Authorization": f"Bearer {token}"}


async def _request(
    method: str,
    path: str,
    token: str,
    *,
    accept: str | None = None,
    json: Any = None,
    params: dict | None = None,
    timeout: int = _DEFAULT_TIMEOUT,
) -> httpx.Response:
    """Single entry point for GitHub REST calls. Raises on non-2xx."""
    headers = _auth(token)
    if accept:
        headers["Accept"] = accept
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.request(method, f"{BASE}{path}", headers=headers, json=json, params=params)
        r.raise_for_status()
        return r


async def _paginate(path: str, token: str) -> list[dict]:
    """Collect all pages of a list endpoint (100 per page)."""
    items: list[dict] = []
    page = 1
    while True:
        r = await _request("GET", path, token, params={"per_page": 100, "page": page})
        batch = r.json()
        if not batch:
            break
        items.extend(batch)
        page += 1
    return items


# --------------------------------------------------------------------------- #
# Pull requests
# --------------------------------------------------------------------------- #

async def get_pull_request(token: str, owner: str, repo: str, pr_number: int) -> dict:
    r = await _request("GET", f"/repos/{owner}/{repo}/pulls/{pr_number}", token)
    return r.json()


async def get_pr_diff(token: str, owner: str, repo: str, pr_number: int) -> str:
    r = await _request(
        "GET",
        f"/repos/{owner}/{repo}/pulls/{pr_number}",
        token,
        accept="application/vnd.github.v3.diff",
        timeout=60,
    )
    return r.text


async def list_pr_files(token: str, owner: str, repo: str, pr_number: int) -> list[dict]:
    return await _paginate(f"/repos/{owner}/{repo}/pulls/{pr_number}/files", token)


async def create_review(
    token: str,
    owner: str,
    repo: str,
    pr_number: int,
    commit_id: str,
    body: str,
    comments: list[dict],
) -> dict:
    r = await _request(
        "POST",
        f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
        token,
        json={"commit_id": commit_id, "body": body, "event": "COMMENT", "comments": comments},
    )
    return r.json()


# --------------------------------------------------------------------------- #
# Comments
# --------------------------------------------------------------------------- #

async def create_issue_comment(
    token: str, owner: str, repo: str, issue_number: int, body: str
) -> dict:
    r = await _request(
        "POST",
        f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
        token,
        json={"body": body},
    )
    return r.json()


async def get_review_comment(token: str, owner: str, repo: str, comment_id: int) -> dict:
    r = await _request("GET", f"/repos/{owner}/{repo}/pulls/comments/{comment_id}", token)
    return r.json()


async def reply_to_review_comment(
    token: str, owner: str, repo: str, pr_number: int, comment_id: int, body: str
) -> dict:
    r = await _request(
        "POST",
        f"/repos/{owner}/{repo}/pulls/{pr_number}/comments/{comment_id}/replies",
        token,
        json={"body": body},
    )
    return r.json()


async def list_review_comments(token: str, owner: str, repo: str, pr_number: int) -> list[dict]:
    return await _paginate(f"/repos/{owner}/{repo}/pulls/{pr_number}/comments", token)


async def list_issue_comments(token: str, owner: str, repo: str, issue_number: int) -> list[dict]:
    return await _paginate(f"/repos/{owner}/{repo}/issues/{issue_number}/comments", token)


async def delete_review_comment(token: str, owner: str, repo: str, comment_id: int) -> None:
    await _request("DELETE", f"/repos/{owner}/{repo}/pulls/comments/{comment_id}", token)


async def delete_issue_comment(token: str, owner: str, repo: str, comment_id: int) -> None:
    await _request("DELETE", f"/repos/{owner}/{repo}/issues/comments/{comment_id}", token)


# --------------------------------------------------------------------------- #
# Reactions (best-effort — failures are swallowed, they only acknowledge UX)
# --------------------------------------------------------------------------- #

async def add_reaction_to_comment(
    token: str, owner: str, repo: str, comment_id: int, content: str = "eyes"
) -> None:
    try:
        await _request(
            "POST",
            f"/repos/{owner}/{repo}/issues/comments/{comment_id}/reactions",
            token,
            accept=_REACTIONS_ACCEPT,
            json={"content": content},
        )
    except Exception as e:
        logger.debug("reaction on issue comment %s failed: %s", comment_id, e)


async def add_reaction_to_review_comment(
    token: str, owner: str, repo: str, comment_id: int, content: str = "eyes"
) -> None:
    try:
        await _request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/comments/{comment_id}/reactions",
            token,
            accept=_REACTIONS_ACCEPT,
            json={"content": content},
        )
    except Exception as e:
        logger.debug("reaction on review comment %s failed: %s", comment_id, e)
