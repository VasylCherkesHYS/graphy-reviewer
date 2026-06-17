from app.config import settings
from app.llm.base import LLMProvider


def _build_provider() -> LLMProvider:
    if settings.llm_provider == "anthropic":
        from app.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider()
    from app.llm.openai_provider import OpenAIProvider

    return OpenAIProvider()


provider: LLMProvider = _build_provider()
