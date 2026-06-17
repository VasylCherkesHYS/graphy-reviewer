import json
import logging

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

from app.config import settings
from app.github.verify import verify_signature
from app.handlers.events import handle_event

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Code Review App")

SUPPORTED_EVENTS = {
    "pull_request",
    "pull_request_review_comment",
    "issue_comment",
    "ping",
}


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(request: Request, background: BackgroundTasks) -> dict:
    body = await request.body()

    signature = request.headers.get("X-Hub-Signature-256", "")
    if not verify_signature(body, settings.github_webhook_secret, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    event = request.headers.get("X-GitHub-Event", "")
    delivery_id = request.headers.get("X-GitHub-Delivery", "")

    if event == "ping":
        return {"ok": True, "msg": "pong"}

    if event not in SUPPORTED_EVENTS:
        return {"ok": True, "msg": f"event {event!r} ignored"}

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Return 200 immediately — process in background
    background.add_task(handle_event, event, payload, delivery_id)
    return {"ok": True}
