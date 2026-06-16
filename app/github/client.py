from typing import Any

import httpx

BASE = "https://api.github.com"
HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def _auth(token: str) -> dict:
    return {**HEADERS, "Authorization": f"Bearer {token}"}


async def get_pull_request(token: str, owner: str, repo: str, pr_number: int) -> dict:
    async with httpx.AsyncClient() as c:
        r = await c.get(
            f"{BASE}/repos/{owner}/{repo}/pulls/{pr_number}",
            headers=_auth(token),
        )
        r.raise_for_status()
        return r.json()


async def get_pr_diff(token: str, owner: str, repo: str, pr_number: int) -> str:
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(
            f"{BASE}/repos/{owner}/{repo}/pulls/{pr_number}",
            headers={**_auth(token), "Accept": "application/vnd.github.v3.diff"},
        )
        r.raise_for_status()
        return r.text


async def list_pr_files(token: str, owner: str, repo: str, pr_number: int) -> list[dict]:
    files: list[dict] = []
    page = 1
    async with httpx.AsyncClient() as c:
        while True:
            r = await c.get(
                f"{BASE}/repos/{owner}/{repo}/pulls/{pr_number}/files",
                headers=_auth(token),
                params={"per_page": 100, "page": page},
            )
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            files.extend(batch)
            page += 1
    return files


async def create_review(
    token: str,
    owner: str,
    repo: str,
    pr_number: int,
    commit_id: str,
    body: str,
    comments: list[dict],
) -> dict:
    async with httpx.AsyncClient() as c:
        r = await c.post(
            f"{BASE}/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
            headers=_auth(token),
            json={
                "commit_id": commit_id,
                "body": body,
                "event": "COMMENT",
                "comments": comments,
            },
        )
        r.raise_for_status()
        return r.json()


async def create_issue_comment(
    token: str, owner: str, repo: str, issue_number: int, body: str
) -> dict:
    async with httpx.AsyncClient() as c:
        r = await c.post(
            f"{BASE}/repos/{owner}/{repo}/issues/{issue_number}/comments",
            headers=_auth(token),
            json={"body": body},
        )
        r.raise_for_status()
        return r.json()


async def get_review_comment(
    token: str, owner: str, repo: str, comment_id: int
) -> dict:
    async with httpx.AsyncClient() as c:
        r = await c.get(
            f"{BASE}/repos/{owner}/{repo}/pulls/comments/{comment_id}",
            headers=_auth(token),
        )
        r.raise_for_status()
        return r.json()


async def reply_to_review_comment(
    token: str,
    owner: str,
    repo: str,
    pr_number: int,
    comment_id: int,
    body: str,
) -> dict:
    async with httpx.AsyncClient() as c:
        r = await c.post(
            f"{BASE}/repos/{owner}/{repo}/pulls/{pr_number}/comments/{comment_id}/replies",
            headers=_auth(token),
            json={"body": body},
        )
        r.raise_for_status()
        return r.json()
