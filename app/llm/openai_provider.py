import logging

import openai

from app.config import settings

logger = logging.getLogger(__name__)


class OpenAIProvider:
    def __init__(self) -> None:
        self._client = openai.AsyncOpenAI(api_key=settings.openai_api_key)

    async def complete(
        self,
        system: str,
        prompt: str,
        *,
        max_tokens: int,
        json_mode: bool = False,
        large: bool = False,
    ) -> str:
        model = settings.openai_complex_model if large else settings.openai_model

        kwargs: dict = {
            "model": model,
            "max_completion_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        resp = await self._client.chat.completions.create(**kwargs)
        content = resp.choices[0].message.content or ""
        return content.strip()
