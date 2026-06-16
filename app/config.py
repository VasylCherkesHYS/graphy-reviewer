from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    github_app_id: str
    github_private_key: str  # PEM contents, newlines as \n
    github_webhook_secret: str
    anthropic_api_key: str

    review_model: str = "claude-sonnet-4-6"
    complex_model: str = "claude-opus-4-8"
    max_diff_chars: int = 120_000
    graph_timeout: int = 120  # seconds
    clone_depth: int = 100


settings = Settings()
