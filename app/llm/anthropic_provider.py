import logging

import anthropic

from app.config import settings

logger = logging.getLogger(__name__)


class AnthropicProvider:
    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def complete(
        self,
        system: str,
        prompt: str,
        *,
        max_tokens: int,
        json_mode: bool = False,
        large: bool = False,
    ) -> str:
        model = settings.complex_model if large else settings.review_model

        # Anthropic has no dedicated JSON mode; the prompt instructs JSON output.
        response = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=[
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
