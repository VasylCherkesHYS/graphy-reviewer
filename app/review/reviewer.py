import json
import logging

import anthropic

from app.config import settings
from app.review.prompts import REVIEW_SYSTEM, build_review_prompt
from app.review.schema import ReviewResult

logger = logging.getLogger(__name__)

_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

_LARGE_DIFF_THRESHOLD = 40_000  # chars


def _pick_model(diff: str) -> str:
    if len(diff) > _LARGE_DIFF_THRESHOLD:
        return settings.complex_model
    return settings.review_model


async def review_pr(diff: str, graph_context: str) -> ReviewResult:
    model = _pick_model(diff)
    prompt = build_review_prompt(diff, graph_context, settings.max_diff_chars)

    logger.info("Running PR review with model=%s diff_len=%d", model, len(diff))

    response = await _client.messages.create(
        model=model,
        max_tokens=16000,
        system=[
            {
                "type": "text",
                "text": REVIEW_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()

    # strip markdown code fences if model wraps JSON
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rsplit("```", 1)[0].strip()

    data = json.loads(raw)
    return ReviewResult.model_validate(data)


async def reply_to_comment(
    original_comment: str,
    diff_hunk: str,
    file_path: str,
    user_reply: str,
) -> str:
    from app.review.prompts import build_dialog_prompt

    prompt = build_dialog_prompt(original_comment, diff_hunk, file_path, user_reply)

    response = await _client.messages.create(
        model=settings.complex_model,
        max_tokens=4000,
        system="Ты — AI code reviewer, ведёшь диалог в треде PR на GitHub.",
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()
