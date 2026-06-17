import logging

from app.review import applier, reviewer
from app.review.schema import ApplyOutcome

logger = logging.getLogger(__name__)


async def apply_finding(repo_dir: str, finding: dict) -> ApplyOutcome:
    """Apply a single review finding to the working tree and commit it.

    Strategy:
      1. Deterministic — if the finding carries a ```suggestion``` block,
         replace exactly the lines it is anchored to.
      2. Fallback — ask the LLM to produce exact-string edits from the
         finding text.

    Pushing is the caller's responsibility (so several findings can be
    committed before a single push).
    """
    file_path: str = finding.get("path", "")
    body: str = finding.get("body", "")

    if not file_path or not applier.file_exists(repo_dir, file_path):
        return ApplyOutcome(applied=False, note=f"файл `{file_path}` не найден в ветке")

    outcome = await _try_suggestion(repo_dir, file_path, body, finding)
    if outcome is not None:
        return outcome

    return await _try_llm_fix(repo_dir, file_path, body)


async def _try_suggestion(
    repo_dir: str, file_path: str, body: str, finding: dict
) -> ApplyOutcome | None:
    """Apply the bot's own suggestion block. Returns None to fall through to the LLM."""
    suggestion = applier.extract_suggestion(body)
    if suggestion is None:
        return None

    end_line = finding.get("line") or finding.get("original_line")
    start_line = (
        finding.get("start_line") or finding.get("original_start_line") or end_line
    )
    if not end_line:
        return None

    try:
        applier.apply_suggestion(
            repo_dir, file_path, int(start_line), int(end_line), suggestion
        )
        sha = applier.commit(
            repo_dir, file_path, f"fix: apply review suggestion in {file_path}"
        )
    except Exception as e:
        logger.warning("Suggestion apply failed (%s), falling back to LLM", e)
        return None

    if sha:
        return ApplyOutcome(applied=True, sha=sha)
    return None


async def _try_llm_fix(repo_dir: str, file_path: str, body: str) -> ApplyOutcome:
    content = applier.read_text(repo_dir, file_path)
    fix = await reviewer.generate_fix(file_path, content, body)

    if not fix.applicable or not fix.edits:
        return ApplyOutcome(
            applied=False, note=fix.note or "правку нельзя применить автоматически"
        )

    target = fix.file or file_path
    applier.apply_edits(repo_dir, target, fix.edits)
    sha = applier.commit(repo_dir, target, fix.commit_message)
    if not sha:
        return ApplyOutcome(applied=False, note="после правки нет изменений")
    return ApplyOutcome(applied=True, sha=sha, note=fix.note)
