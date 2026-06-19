REVIEW_GUIDELINES = """\
# Review Guidelines (EpicStaff)

Rubric for AI review of pull requests. This is the **only** source of review rules.

> ⚠️ The rules in the root CLAUDE.md (backend-only, "don't touch the frontend", "don't commit")
> describe interactive development, NOT review — they do not apply to review.
> Use the architectural part of CLAUDE.md (what the services are, how the flow runs, Redis/Postgres) as context.

## Review scope
Review both frontend and backend — every changed file in the PR:
- Backend — Django (tables), the crew, knowledge, manager, realtime, webhook microservices, src/shared.
- Frontend — Angular 19 SPA (frontend/).

## What to look for — Backend
- Correctness and regressions: logic errors, unhandled exceptions, race conditions.
- DB schema compatibility: the same Postgres is read by crew/knowledge/manager/realtime. Any model/migration change must be backward compatible.
- Layering: business logic belongs in services/, not in views/serializers/models.
- Vendored code (src/crew/libraries/, src/knowledge/libraries/graphrag) must not be patched — extend it via services/.
- Redis channels: declare names centrally, do not inline them.
- Security: injections, secret leaks, missing permission checks (RBAC in tables/services/rbac/).
- Migrations: generated via makemigrations, not hand-written.

## What to look for — Frontend (Angular 19)
- Correctness: RxJS subscriptions without leaks (takeUntilDestroyed/async), unsubscribe in ngOnDestroy.
- Change detection: needless re-renders, OnPush correctness, mutation of input data.
- Type safety: no any, correct DTO types for the API.
- API consistency: frontend DTOs match backend schema/serializer changes.

## Output format
- Inline comments only where there is a real problem. Do not comment on style for the sake of style.
- Every finding carries a severity: [critical] / [major] / [minor] / [nit].
- Create a SEPARATE finding for EACH problem — do not group them.
- line — the line number in the NEW version of the file (the right side of the diff).
- ALWAYS, when a problem has a concrete fix, add a `suggestion` field —
  this is the FULL fixed code for EXACTLY the lines the comment points at
  (from `start_line` through `line`, inclusive). If the fix spans several lines,
  set `start_line` (the first line of the range); for a single line, `start_line` may be omitted.
  `suggestion` must fully replace those lines (no diff, no ```), with correct indentation.
  If there is no concrete safe fix (context outside those lines is needed) — leave `suggestion` empty/null.
- At the end, provide a separate overall summary for the maintainer: what the PR does, key changes, risks, verdict.
- Write comments in English.
"""

REVIEW_SYSTEM = (
    "You are an AI code reviewer. You receive a pull request diff and dependency-graph context. "
    "Follow the review rubric strictly. Return ONLY valid JSON matching the given schema — "
    "findings[], summary, graph_used, graph_evidence. No text outside the JSON."
)


def build_review_prompt(diff: str, graph_context: str, max_diff_chars: int) -> str:
    truncated_diff = diff[:max_diff_chars]
    if len(diff) > max_diff_chars:
        truncated_diff += f"\n\n... [diff truncated at {max_diff_chars} chars]"

    return (
        f"{REVIEW_GUIDELINES}\n\n"
        f"=== PR DIFF ===\n{truncated_diff}\n\n"
        f"=== GRAPH CONTEXT (blast radius) ===\n{graph_context}\n\n"
        "Return STRICT JSON matching the schema: findings[] "
        "(path, line, severity, title, body, start_line?, suggestion?), "
        "summary, graph_used (bool), graph_evidence."
    )


def build_dialog_prompt(
    original_comment: str,
    diff_hunk: str,
    file_path: str,
    user_reply: str,
) -> str:
    return (
        f"You left a comment on the file `{file_path}`:\n\n"
        f"{original_comment}\n\n"
        f"Code context (diff hunk):\n```\n{diff_hunk}\n```\n\n"
        f"The developer replied:\n{user_reply}\n\n"
        "Respond on the merits: if the developer is right — acknowledge it; if not — explain concretely why. "
        "Answer in English, briefly and to the point."
    )


FIX_SYSTEM = (
    "You are an AI engineer applying a previously suggested fix to a single file. "
    "You receive the full file contents and the text of the review comment. "
    "Return ONLY valid JSON matching the schema: "
    '{"file": str, "edits": [{"old": str, "new": str}], "commit_message": str, '
    '"note": str, "applicable": bool}. '
    "Rule for edits: 'old' is an EXACT substring of the current file (matching indentation and whitespace) "
    "that occurs in the file EXACTLY once; 'new' is what to replace it with. "
    "Make minimal edits, do not rewrite the whole file. "
    "commit_message — a short commit message in English, in Conventional Commits style. "
    "If the fix cannot be applied safely (context outside the file is needed, it is ambiguous, etc.) — "
    'return "applicable": false, an empty edits list, and explain the reason in note (in English). '
    "No text outside the JSON."
)


def build_fix_prompt(file_path: str, file_content: str, finding_text: str) -> str:
    return (
        f"File: `{file_path}`\n\n"
        f"=== REVIEWER COMMENT ===\n{finding_text}\n\n"
        f"=== CURRENT FILE CONTENTS ===\n{file_content}\n\n"
        "Produce edits that implement this comment. "
        "Remember: each 'old' must match the file exactly and unambiguously."
    )
