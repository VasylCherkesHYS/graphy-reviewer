from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # GitHub App
    github_app_id: str
    github_private_key: str = ""  # PEM contents inline, newlines as \n
    github_private_key_path: str = ""  # path to a PEM file (takes precedence)
    github_webhook_secret: str

    # LLM provider selection
    llm_provider: Literal["openai", "anthropic"] = "openai"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1"
    openai_complex_model: str = "gpt-4.1"

    # Anthropic
    anthropic_api_key: str = ""
    review_model: str = "claude-sonnet-4-6"
    complex_model: str = "claude-opus-4-8"

    # Behaviour
    auto_review_on_request: bool = True  # review when bot is added as a reviewer
    auto_review_on_open: bool = False    # review automatically on PR open/sync
    delete_resolved_comments: bool = True  # delete a finding's comment once its fix is applied
    max_diff_chars: int = 120_000
    graph_timeout: int = 120  # seconds
    clone_depth: int = 100

    # Git identity used when the bot commits applied fixes
    git_author_name: str = "reviewer-bot-agent[bot]"
    git_author_email: str = "reviewer-bot-agent[bot]@users.noreply.github.com"

    @model_validator(mode="after")
    def _check_provider_key(self) -> "Settings":
        if self.llm_provider == "openai" and not self.openai_api_key:
            raise ValueError("LLM_PROVIDER=openai requires OPENAI_API_KEY")
        if self.llm_provider == "anthropic" and not self.anthropic_api_key:
            raise ValueError("LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY")
        if not self.github_private_key and not self.github_private_key_path:
            raise ValueError(
                "Set either GITHUB_PRIVATE_KEY (inline PEM) or GITHUB_PRIVATE_KEY_PATH (PEM file)"
            )
        return self

    @property
    def private_key_pem(self) -> str:
        """PEM contents of the GitHub App private key.

        Reads from GITHUB_PRIVATE_KEY_PATH if set (file takes precedence),
        otherwise uses the inline GITHUB_PRIVATE_KEY (with escaped newlines).
        """
        if self.github_private_key_path:
            return Path(self.github_private_key_path).read_text(encoding="utf-8")
        return self.github_private_key.replace("\\n", "\n")


settings = Settings()
