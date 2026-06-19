import json
import logging

from app.config import settings
from app.llm import provider
from app.review.prompts import (
    FIX_SYSTEM,
    REVIEW_SYSTEM,
    build_dialog_prompt,
    build_fix_prompt,
    build_review_prompt,
)
from app.review.schema import FixEdit, ReviewResult

logger = logging.getLogger(__name__)

_LARGE_DIFF_THRESHOLD = 40_000  # chars


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    # strip markdown code fences if the model wraps JSON
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rsplit("```", 1)[0].strip()
    return json.loads(raw)


async def review_pr(diff: str, graph_context: str) -> ReviewResult:
    large = len(diff) > _LARGE_DIFF_THRESHOLD
    prompt = build_review_prompt(diff, graph_context, settings.max_diff_chars)

    logger.info(
        "Running PR review provider=%s large=%s diff_len=%d",
        settings.llm_provider,
        large,
        len(diff),
    )

    raw = await provider.complete(
        REVIEW_SYSTEM, prompt, max_tokens=16000, json_mode=True, large=large
    )
    data = _parse_json(raw)
    return ReviewResult.model_validate(data)


async def reply_to_comment(
    original_comment: str,
    diff_hunk: str,
    file_path: str,
    user_reply: str,
) -> str:
    prompt = build_dialog_prompt(original_comment, diff_hunk, file_path, user_reply)
    return await provider.complete(
        "You are an AI code reviewer holding a discussion in a PR thread on GitHub.",
        prompt,
        max_tokens=4000,
        large=True,
    )


async def generate_fix(file_path: str, file_content: str, finding_text: str) -> FixEdit:
    prompt = build_fix_prompt(file_path, file_content, finding_text)
    raw = await provider.complete(
        FIX_SYSTEM, prompt, max_tokens=8000, json_mode=True, large=True
    )
    data = _parse_json(raw)
    return FixEdit.model_validate(data)
