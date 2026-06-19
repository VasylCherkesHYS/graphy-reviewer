"""Test bootstrap: set the env vars Settings() requires BEFORE app.config loads,
and override anything the on-disk .env might set, so tests are deterministic.
"""
import os

os.environ.setdefault("GITHUB_APP_ID", "12345")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-secret")
os.environ["LLM_PROVIDER"] = "openai"
os.environ["OPENAI_API_KEY"] = "test-openai-key"
os.environ["GITHUB_PRIVATE_KEY"] = (
    "-----BEGIN PRIVATE KEY-----\\ntest\\n-----END PRIVATE KEY-----"
)
os.environ.pop("GITHUB_PRIVATE_KEY_PATH", None)
