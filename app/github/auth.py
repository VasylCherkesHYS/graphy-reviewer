import time
from typing import Optional

import httpx
import jwt

from app.config import settings

_token_cache: dict[int, tuple[str, float]] = {}


def _make_app_jwt() -> str:
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 540, "iss": settings.github_app_id}
    return jwt.encode(payload, settings.private_key_pem, algorithm="RS256")


async def get_installation_token(installation_id: int) -> str:
    cached_token, expires_at = _token_cache.get(installation_id, ("", 0.0))
    if cached_token and time.time() < expires_at - 300:
        return cached_token

    app_jwt = _make_app_jwt()
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"https://api.github.com/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        r.raise_for_status()
        data = r.json()

    token: str = data["token"]
    # expires_at format: "2024-01-01T00:00:00Z"
    from datetime import datetime, timezone
    exp_str: str = data.get("expires_at", "")
    try:
        exp_dt = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
        exp_ts = exp_dt.timestamp()
    except Exception:
        exp_ts = time.time() + 3600

    _token_cache[installation_id] = (token, exp_ts)
    return token
