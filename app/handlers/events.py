import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.config import settings
from app.github import client as gh
from app.github.auth import get_installation_token
from app.github.payload import PushCtx, RepoCtx, head_target
from app.review import applier, clone, fix_service, graph, graph_cache, poster, reviewer

logger = logging.getLogger(__name__)

# Simple in-memory dedup: last 500 delivery IDs
_seen_deliveries: set[str] = set()
_seen_order: list[str] = []

# Per-repo locks serialize graph rebuilds (rapid pushes run sequentially).
_refresh_locks: dict[str, asyncio.Lock] = {}


def _refresh_lock(owner: str, repo: str) -> asyncio.Lock:
    key = f"{owner}/{repo}"
    lock = _refresh_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _refresh_locks[key] = lock
    return lock


def _is_duplicate(delivery_id: str) -> bool:
    if delivery_id in _seen_deliveries:
        return True
    _seen_deliveries.add(delivery_id)
    _seen_order.append(delivery_id)
    if len(_seen_order) > 500:
        old = _seen_order.pop(0)
        _seen_deliveries.discard(old)
    return False


def _is_bot(actor: dict) -> bool:
    return actor.get("type") == "Bot" or "[bot]" in actor.get("login", "")


async def handle_event(event: str, payload: dict, delivery_id: str) -> None:
    if _is_duplicate(delivery_id):
        logger.info("Duplicate delivery %s, skipping", delivery_id)
        return

    if event == "pull_request":
        action = payload.get("action", "")
        if action == "review_requested" and settings.auto_review_on_request:
            if _is_bot(payload.get("requested_reviewer", {})):
                await _handle_pr_review(payload)
        elif action in ("opened", "synchronize", "reopened") and settings.auto_review_on_open:
            await _handle_pr_review(payload)

    elif event == "issue_comment":
        if payload.get("action") == "created":
            await _handle_issue_comment(payload)

    elif event == "pull_request_review_comment":
        if payload.get("action") == "created":
            await _handle_review_comment(payload)

    elif event == "push":
        await _handle_push(payload)


# --------------------------------------------------------------------------- #
# Graph refresh on push to the default branch
# --------------------------------------------------------------------------- #

async def _handle_push(payload: dict) -> None:
    if not settings.refresh_graph_on_push:
        return
    ctx = PushCtx.from_payload(payload)
    if ctx.deleted or not ctx.is_default_branch:
        return
    if ctx.sender_is_bot:
        logger.info("Push by bot on %s/%s — skipping graph refresh", ctx.owner, ctx.repo)
        return
    await _refresh_graph(ctx)


async def _refresh_graph(ctx: PushCtx) -> None:
    """Rebuild the graph (+ embeddings) from the default branch and cache it.

    Best-effort: any failure is logged and never surfaces to users. Serialized
    per repo so concurrent pushes don't rebuild on top of each other.
    """
    async with _refresh_lock(ctx.owner, ctx.repo):
        logger.info("Graph refresh started: %s/%s @ %s", ctx.owner, ctx.repo, ctx.after[:7])
        token = await get_installation_token(ctx.installation_id)
        tmp = None
        try:
            ref = f"refs/heads/{ctx.default_branch}"
            tmp = clone.clone_repo(token, ctx.owner, ctx.repo, ref, ctx.after, depth=settings.clone_depth)
            # Seed from the previous cache so `update` + `embed` stay incremental.
            graph_cache.restore_from_cache(tmp, token, ctx.owner, ctx.repo, settings.graph_cache_branch)
            if not graph.ensure_graph(tmp):
                logger.warning("Graph refresh: build/update failed, aborting")
                return
            graph.build_embeddings(tmp)
            if graph_cache.save_to_cache(tmp, token, ctx.owner, ctx.repo, settings.graph_cache_branch):
                logger.info("Graph refresh done: %s/%s", ctx.owner, ctx.repo)
        except Exception as e:
            logger.warning("Graph refresh failed: %s", e)
        finally:
            if tmp:
                clone.cleanup(tmp)


# --------------------------------------------------------------------------- #
# Review
# --------------------------------------------------------------------------- #

async def _handle_pr_review(payload: dict) -> None:
    ctx = RepoCtx.from_payload(payload)
    pr = payload["pull_request"]
    token = await get_installation_token(ctx.installation_id)
    await _run_review(token, ctx.owner, ctx.repo, pr["number"], pr["base"]["sha"], pr["head"]["sha"])


async def _run_review(
    token: str, owner: str, repo: str, pr_number: int, base_sha: str, head_sha: str
) -> None:
    logger.info("PR review started: %s/%s#%d", owner, repo, pr_number)

    diff = await gh.get_pr_diff(token, owner, repo, pr_number)

    tmp = None
    graph_context = graph.FALLBACK
    semantic_context = graph.FALLBACK_SEMANTIC
    try:
        ref = f"refs/pull/{pr_number}/head"
        tmp = clone.clone_repo(token, owner, repo, ref, base_sha, depth=settings.clone_depth)
        # Reuse the persistent graph from the cache branch; `ensure_graph` then
        # incrementally updates it with the PR's changed files (or builds from
        # scratch on a cache miss).
        graph_cache.restore_from_cache(tmp, token, owner, repo, settings.graph_cache_branch)
        if graph.ensure_graph(tmp):
            graph.build_embeddings(tmp)
            graph_context = graph.detect_changes(tmp, base_sha)
            semantic_context = graph.semantic_context(tmp, diff)
    except Exception as e:
        logger.warning("Graph step failed: %s", e)
    finally:
        if tmp:
            clone.cleanup(tmp)

    result = await reviewer.review_pr(diff, graph_context, semantic_context)
    await poster.post_review(token, owner, repo, pr_number, head_sha, result)
    logger.info("PR review done: %s/%s#%d findings=%d", owner, repo, pr_number, len(result.findings))


# --------------------------------------------------------------------------- #
# PR conversation commands (/review, /apply-all, /cleanup, /help)
# --------------------------------------------------------------------------- #

_HELP_TEXT = (
    "🤖 **AI Code Review — commands**\n\n"
    "- `/review` — run (or re-run) the PR review.\n"
    "- `/apply` — _as a reply in the thread of a specific finding_: apply the suggested fix, "
    "commit it, and push to the PR branch (the finding is closed afterwards).\n"
    "- `/apply-all` — apply all of my findings (each as a separate commit).\n"
    "- `/cleanup` — delete all of my comments in this PR.\n"
    "- Any other reply in the thread of my finding — continues the discussion.\n\n"
    "💡 For findings with a _suggestion_ block you can click **\"Commit suggestion\"** right in GitHub."
)


async def _cmd_review(token: str, ctx: RepoCtx, pr_number: int) -> None:
    pr = await gh.get_pull_request(token, ctx.owner, ctx.repo, pr_number)
    await _run_review(token, ctx.owner, ctx.repo, pr_number, pr["base"]["sha"], pr["head"]["sha"])


async def _cmd_help(token: str, ctx: RepoCtx, pr_number: int) -> None:
    await gh.create_issue_comment(token, ctx.owner, ctx.repo, pr_number, _HELP_TEXT)


# prefix(es) -> handler. Order matters: first match wins.
_COMMANDS: list[tuple[tuple[str, ...], Callable[[str, RepoCtx, int], Awaitable[None]]]] = [
    (("/review",), _cmd_review),
    (("/apply-all", "/apply all"), lambda t, c, n: _apply_all(t, c, n)),
    (("/cleanup", "/clear"), lambda t, c, n: _cleanup(t, c, n)),
    (("/help",), _cmd_help),
]


def _match_command(command: str):
    for prefixes, handler in _COMMANDS:
        if any(command.startswith(p) for p in prefixes):
            return handler
    return None


async def _handle_issue_comment(payload: dict) -> None:
    issue = payload.get("issue", {})
    if "pull_request" not in issue:
        return  # comment on a plain issue, not a PR
    if _is_bot(payload.get("sender", {})):
        return

    command = payload["comment"]["body"].strip().lower()
    handler = _match_command(command)
    if handler is None:
        return

    ctx = RepoCtx.from_payload(payload)
    pr_number: int = issue["number"]
    token = await get_installation_token(ctx.installation_id)
    await gh.add_reaction_to_comment(token, ctx.owner, ctx.repo, payload["comment"]["id"], "eyes")
    await handler(token, ctx, pr_number)


async def _cleanup(token: str, ctx: RepoCtx, pr_number: int) -> None:
    owner, repo = ctx.owner, ctx.repo
    deleted = 0
    try:
        for c in await gh.list_review_comments(token, owner, repo, pr_number):
            if _is_bot(c.get("user", {})):
                try:
                    await gh.delete_review_comment(token, owner, repo, c["id"])
                    deleted += 1
                except Exception:
                    pass
        for c in await gh.list_issue_comments(token, owner, repo, pr_number):
            if _is_bot(c.get("user", {})):
                try:
                    await gh.delete_issue_comment(token, owner, repo, c["id"])
                    deleted += 1
                except Exception:
                    pass
    except Exception as e:
        logger.warning("cleanup failed: %s", e)

    await gh.create_issue_comment(token, owner, repo, pr_number, f"🧹 Deleted {deleted} of my comments.")
    logger.info("cleanup done: deleted %d comments on %s#%d", deleted, repo, pr_number)


# --------------------------------------------------------------------------- #
# Inline review-comment commands & dialog
# --------------------------------------------------------------------------- #

async def _handle_review_comment(payload: dict) -> None:
    comment = payload["comment"]
    if _is_bot(payload["sender"]):
        return

    body: str = comment.get("body", "").strip()
    if body.lower().startswith("/apply"):
        await _apply_one(payload)
        return

    # Otherwise: dialog. Only reply to threads on our own comments.
    in_reply_to_id: int | None = comment.get("in_reply_to_id")
    if not in_reply_to_id:
        return

    ctx = RepoCtx.from_payload(payload)
    pr_number: int = payload["pull_request"]["number"]
    token = await get_installation_token(ctx.installation_id)

    try:
        original = await gh.get_review_comment(token, ctx.owner, ctx.repo, in_reply_to_id)
    except Exception as e:
        logger.warning("Could not fetch parent comment %d: %s", in_reply_to_id, e)
        return

    if not _is_bot(original.get("user", {})):
        return

    reply_text = await reviewer.reply_to_comment(
        original_comment=original["body"],
        diff_hunk=comment.get("diff_hunk", ""),
        file_path=comment.get("path", ""),
        user_reply=body,
    )
    await gh.reply_to_review_comment(token, ctx.owner, ctx.repo, pr_number, comment["id"], reply_text)
    logger.info("Dialog reply posted on comment %d", comment["id"])


async def _apply_one(payload: dict) -> None:
    comment = payload["comment"]
    ctx = RepoCtx.from_payload(payload)
    owner, repo = ctx.owner, ctx.repo
    pr = payload["pull_request"]
    pr_number: int = pr["number"]

    token = await get_installation_token(ctx.installation_id)
    await gh.add_reaction_to_review_comment(token, owner, repo, comment["id"], "eyes")

    # The suggestion lives in the bot's original finding (the parent of this reply).
    in_reply_to_id: int | None = comment.get("in_reply_to_id")
    finding: dict | None = None
    if in_reply_to_id:
        try:
            finding = await gh.get_review_comment(token, owner, repo, in_reply_to_id)
        except Exception as e:
            logger.warning("Could not fetch parent finding %s: %s", in_reply_to_id, e)

    if not finding or not _is_bot(finding.get("user", {})):
        await gh.reply_to_review_comment(
            token, owner, repo, pr_number, comment["id"],
            "Couldn't find the original finding. Reply with `/apply` in the thread of my comment.",
        )
        return

    head_owner, head_name, branch = head_target(pr, owner, repo)

    tmp = None
    try:
        tmp = clone.clone_branch(token, head_owner, head_name, branch, depth=settings.clone_depth)
        outcome = await fix_service.apply_finding(tmp, finding)
        if not outcome.applied:
            await gh.reply_to_review_comment(
                token, owner, repo, pr_number, comment["id"],
                f"⚠️ Couldn't apply the fix automatically: {outcome.note}",
            )
            return
        applier.push(tmp, branch)
        logger.info("Applied fix on %s#%d commit=%s", repo, pr_number, outcome.sha)

        note = f"\n\n{outcome.note}" if outcome.note else ""
        if settings.delete_resolved_comments:
            await gh.create_issue_comment(
                token, owner, repo, pr_number,
                f"✅ Applied the fix to `{finding.get('path', '')}` — commit `{outcome.sha}` "
                f"on branch `{branch}`. Finding closed.{note}",
            )
            try:
                await gh.delete_review_comment(token, owner, repo, finding["id"])
            except Exception as e:
                logger.warning("Could not delete resolved finding %s: %s", finding["id"], e)
        else:
            await gh.reply_to_review_comment(
                token, owner, repo, pr_number, comment["id"],
                f"✅ Applied the fix and pushed commit `{outcome.sha}` to branch `{branch}`.{note}",
            )
    except Exception as e:
        logger.warning("Apply failed: %s", e)
        await gh.reply_to_review_comment(
            token, owner, repo, pr_number, comment["id"],
            f"❌ Error while applying the fix: {e}",
        )
    finally:
        if tmp:
            clone.cleanup(tmp)


async def _apply_all(token: str, ctx: RepoCtx, pr_number: int) -> None:
    owner, repo = ctx.owner, ctx.repo
    comments = await gh.list_review_comments(token, owner, repo, pr_number)
    findings = [
        c for c in comments
        if poster.FINDING_MARKER in c.get("body", "") and _is_bot(c.get("user", {}))
    ]

    if not findings:
        await gh.create_issue_comment(
            token, owner, repo, pr_number,
            "Couldn't find any of my findings to apply. Run `/review` first.",
        )
        return

    pr = await gh.get_pull_request(token, owner, repo, pr_number)
    head_owner, head_name, branch = head_target(pr, owner, repo)

    applied: list[str] = []
    skipped: list[str] = []
    resolved_ids: list[int] = []
    tmp = None
    try:
        tmp = clone.clone_branch(token, head_owner, head_name, branch, depth=settings.clone_depth)
        for c in findings:
            path = c.get("path", "")
            try:
                outcome = await fix_service.apply_finding(tmp, c)
                if outcome.applied:
                    applied.append(f"`{path}` → `{outcome.sha}`")
                    resolved_ids.append(c["id"])
                else:
                    skipped.append(f"`{path}`: {outcome.note}")
            except Exception as e:
                skipped.append(f"`{path}`: {e}")

        if applied:
            applier.push(tmp, branch)
    except Exception as e:
        await gh.create_issue_comment(token, owner, repo, pr_number, f"❌ Error while applying the fixes: {e}")
        return
    finally:
        if tmp:
            clone.cleanup(tmp)

    if settings.delete_resolved_comments:
        for cid in resolved_ids:
            try:
                await gh.delete_review_comment(token, owner, repo, cid)
            except Exception as e:
                logger.warning("Could not delete resolved finding %s: %s", cid, e)

    body = f"🤖 **Applying fixes** — applied {len(applied)} of {len(findings)}.\n\n"
    if applied:
        body += "**Committed:**\n" + "\n".join(f"- {a}" for a in applied) + "\n\n"
    if skipped:
        body += "**Skipped:**\n" + "\n".join(f"- {s}" for s in skipped) + "\n"
    await gh.create_issue_comment(token, owner, repo, pr_number, body)
    logger.info("apply-all done: %d applied, %d skipped", len(applied), len(skipped))
