import logging

from app.github import client as gh
from app.review.schema import Finding, ReviewResult

logger = logging.getLogger(__name__)

_BOT_HEADER = "🤖 **AI Code Review**"

# Hidden marker so the bot can recognise its own findings later (e.g. on /apply-all).
FINDING_MARKER = "<!-- ai-review-finding -->"


def _finding_body(f: Finding) -> str:
    body = f"**[{f.severity}] {f.title}**\n\n{f.body}"
    if f.suggestion is not None and f.suggestion.strip() != "":
        body += f"\n\n```suggestion\n{f.suggestion}\n```"
    body += (
        f"\n\n{FINDING_MARKER}\n"
        f"<sub>To apply: the \"Commit suggestion\" button above, or reply `/apply` in this thread.</sub>"
    )
    return body


def _inline_comment(f: Finding) -> dict:
    comment: dict = {
        "path": f.path,
        "line": f.line,
        "side": "RIGHT",
        "body": _finding_body(f),
    }
    # Multi-line suggestion: anchor the comment across the whole range.
    if f.start_line is not None and f.start_line < f.line:
        comment["start_line"] = f.start_line
        comment["start_side"] = "RIGHT"
    return comment


async def post_review(
    token: str,
    owner: str,
    repo: str,
    pr_number: int,
    commit_id: str,
    result: ReviewResult,
) -> None:
    inline_comments = [_inline_comment(f) for f in result.findings]

    leftover: list[Finding] = []

    # Try posting all as a single batched review; fall back per-comment on 422
    try:
        await gh.create_review(
            token, owner, repo, pr_number, commit_id,
            body="",  # summary posted separately below
            comments=inline_comments,
        )
    except Exception as e:
        logger.warning("Batch review failed (%s), falling back to per-comment", e)
        for f, comment in zip(result.findings, inline_comments):
            try:
                await gh.create_review(
                    token, owner, repo, pr_number, commit_id,
                    body="", comments=[comment],
                )
            except Exception:
                leftover.append(f)

    # Summary comment for the curator
    graph_line = ""
    if result.graph_used:
        graph_line = f"\n\n**Knowledge graph:** {result.graph_evidence}"
    elif result.graph_evidence:
        graph_line = f"\n\n**Graph:** {result.graph_evidence}"

    inline_count = len(result.findings) - len(leftover)
    summary_body = (
        f"{_BOT_HEADER}\n\n"
        f"**Findings:** {len(result.findings)} "
        f"(inline: {inline_count})"
        f"{graph_line}\n\n"
        f"## Summary for the maintainer\n{result.summary}"
    )

    if leftover:
        summary_body += "\n\n## Findings outside the diff (inline posting failed)\n"
        for f in leftover:
            summary_body += f"- **[{f.severity}]** `{f.path}:{f.line}` — {f.title}: {f.body}\n"

    await gh.create_issue_comment(token, owner, repo, pr_number, summary_body)
    logger.info("Review posted: %d findings, %d leftover", len(result.findings), len(leftover))
