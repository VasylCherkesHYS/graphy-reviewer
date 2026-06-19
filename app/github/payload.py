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


@dataclass(frozen=True)
class PushCtx:
    """Identifiers extracted from a `push` webhook payload."""

    installation_id: int
    owner: str
    repo: str
    ref: str  # e.g. "refs/heads/main"
    after: str  # the new tip SHA
    default_branch: str  # e.g. "main"
    deleted: bool
    sender_is_bot: bool

    @classmethod
    def from_payload(cls, payload: dict) -> "PushCtx":
        repo_data = payload["repository"]
        sender = payload.get("sender") or {}
        return cls(
            installation_id=payload["installation"]["id"],
            owner=repo_data["owner"]["login"],
            repo=repo_data["name"],
            ref=payload.get("ref", ""),
            after=payload.get("after", ""),
            default_branch=repo_data.get("default_branch", ""),
            deleted=bool(payload.get("deleted", False)),
            sender_is_bot=(
                sender.get("type") == "Bot" or "[bot]" in (sender.get("login") or "")
            ),
        )

    @property
    def is_default_branch(self) -> bool:
        return bool(self.default_branch) and self.ref == f"refs/heads/{self.default_branch}"


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
