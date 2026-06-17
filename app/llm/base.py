from typing import Protocol


class LLMProvider(Protocol):
    """Minimal text-completion interface shared by OpenAI and Anthropic backends."""

    async def complete(
        self,
        system: str,
        prompt: str,
        *,
        max_tokens: int,
        json_mode: bool = False,
        large: bool = False,
    ) -> str:
        """Return the model's text response.

        - json_mode: ask the provider for a strict JSON object response when supported.
        - large: use the heavier/"complex" model for big or hard inputs.
        """
        ...
