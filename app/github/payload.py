from dataclasses import dataclass


@dataclass(frozen=True)
class RepoCtx:
    """Common identifiers extracted from any installation webhook payload."""

    installation_id: int
    owner: str
    repo: str

    @classmethod
    def from_payload(cls, payload: dict) -> "RepoCtx":
        repo_data = payload["repository"]
        return cls(
            installation_id=payload["installation"]["id"],
            owner=repo_data["owner"]["login"],
            repo=repo_data["name"],
        )


def head_target(pr: dict, fallback_owner: str, fallback_repo: str) -> tuple[str, str, str]:
    """(owner, repo, branch) of the PR head branch — may live in a fork.

    Falls back to the base repo identifiers if the head repo is missing
    (e.g. a deleted fork), matching the previous inline behaviour.
    """
    head = pr["head"]
    head_repo = head.get("repo") or {}
    owner = head_repo.get("owner", {}).get("login", fallback_owner)
    name = head_repo.get("name", fallback_repo)
    return owner, name, head["ref"]
