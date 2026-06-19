import json
import logging
from html import escape

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from app.config import settings
from app.github.verify import verify_signature
from app.handlers.events import handle_event
from app.monitoring import log_buffer, monitor, summarize_payload

# Root logging: console + in-memory ring buffer (exposed at /logs).
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
log_buffer.setFormatter(logging.Formatter(_LOG_FORMAT))
logging.basicConfig(level=settings.log_level.upper(), format=_LOG_FORMAT)
logging.getLogger().addHandler(log_buffer)
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Code Review App")

SUPPORTED_EVENTS = {
    "pull_request",
    "pull_request_review_comment",
    "issue_comment",
    "push",
    "ping",
}


def _check_observability_token(request: Request, token: str | None) -> None:
    """Guard the observability endpoints when OBSERVABILITY_TOKEN is configured."""
    expected = settings.observability_token
    if not expected:
        return
    provided = token or request.headers.get("X-Observability-Token", "")
    if provided != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing observability token")


async def _tracked_handle_event(event: str, payload: dict, delivery_id: str) -> None:
    """Run the real handler, recording success/failure for the /events view."""
    try:
        await handle_event(event, payload, delivery_id)
        monitor.finish(delivery_id, "ok")
    except Exception as e:  # noqa: BLE001 — we want to surface any handler failure
        logger.exception("Handler failed for delivery %s (%s)", delivery_id, event)
        monitor.finish(delivery_id, "error", error=f"{type(e).__name__}: {e}")


# --------------------------------------------------------------------------- #
# Webhook
# --------------------------------------------------------------------------- #

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
        monitor.start(delivery_id, event)
        monitor.finish(delivery_id, "skipped", error=f"event {event!r} not supported")
        return {"ok": True, "msg": f"event {event!r} ignored"}

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    action, repo, pr = summarize_payload(event, payload)
    monitor.start(delivery_id, event, action=action, repo=repo, pr=pr)
    logger.info("Webhook received: event=%s action=%s repo=%s pr=%s delivery=%s",
                event, action, repo, pr, delivery_id)

    # Return 200 immediately — process in background.
    background.add_task(_tracked_handle_event, event, payload, delivery_id)
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Observability
# --------------------------------------------------------------------------- #

@app.get("/healthz")
async def healthz() -> dict:
    """Liveness + lightweight stats (kept backward-compatible: still has status=ok)."""
    return monitor.snapshot_stats()


@app.get("/stats")
async def stats(request: Request, token: str | None = Query(default=None)) -> dict:
    _check_observability_token(request, token)
    return monitor.snapshot_stats()


@app.get("/events")
async def events(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
    token: str | None = Query(default=None),
) -> dict:
    _check_observability_token(request, token)
    return {"events": monitor.recent(limit=limit, status=status)}


@app.get("/logs")
async def logs(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    level: str | None = Query(default=None),
    token: str | None = Query(default=None),
) -> dict:
    _check_observability_token(request, token)
    return {"lines": log_buffer.lines(limit=limit, level=level)}


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, token: str | None = Query(default=None)) -> str:
    _check_observability_token(request, token)
    stats_data = monitor.snapshot_stats()
    deliveries = monitor.recent(limit=50)
    log_lines = log_buffer.lines(limit=100)

    c = stats_data["counters"]
    rows = "".join(
        f"<tr class='{escape(d['status'])}'>"
        f"<td>{escape(d['received_at'])}</td>"
        f"<td>{escape(d['event'])}</td>"
        f"<td>{escape(str(d.get('action') or ''))}</td>"
        f"<td>{escape(str(d.get('repo') or ''))}</td>"
        f"<td>{escape(str(d.get('pr') or ''))}</td>"
        f"<td><b>{escape(d['status'])}</b></td>"
        f"<td>{escape(str(d.get('duration_ms') or ''))}</td>"
        f"<td>{escape(str(d.get('error') or ''))}</td>"
        "</tr>"
        for d in deliveries
    ) or "<tr><td colspan='8'>No deliveries yet.</td></tr>"

    logs_html = escape("\n".join(log_lines)) or "(no logs yet)"

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>AI Code Review — monitor</title>
<meta http-equiv="refresh" content="5">
<style>
  body {{ font: 14px/1.5 system-ui, sans-serif; margin: 1.5rem; color: #1a1a1a; }}
  h1 {{ font-size: 1.2rem; }}
  .cards {{ display: flex; gap: 1rem; flex-wrap: wrap; margin: 1rem 0; }}
  .card {{ background: #f4f4f5; border-radius: 8px; padding: .75rem 1.1rem; }}
  .card b {{ font-size: 1.4rem; display: block; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th, td {{ text-align: left; padding: 4px 8px; border-bottom: 1px solid #e5e5e5; vertical-align: top; }}
  tr.error {{ background: #fdecea; }}
  tr.skipped {{ color: #888; }}
  pre {{ background: #1e1e1e; color: #d4d4d4; padding: 1rem; border-radius: 8px;
        overflow: auto; max-height: 360px; font-size: 12px; }}
  .muted {{ color: #888; }}
</style></head>
<body>
  <h1>AI Code Review — monitor <span class="muted">(auto-refresh 5s)</span></h1>
  <p class="muted">uptime {stats_data['uptime_seconds']}s · started {escape(stats_data['started_at'])}</p>
  <div class="cards">
    <div class="card"><b>{c['received']}</b>received</div>
    <div class="card"><b>{c['ok']}</b>ok</div>
    <div class="card"><b>{c['error']}</b>errors</div>
    <div class="card"><b>{c['skipped']}</b>skipped</div>
  </div>
  <h2 style="font-size:1rem">Recent deliveries</h2>
  <table>
    <tr><th>time (UTC)</th><th>event</th><th>action</th><th>repo</th><th>PR</th>
        <th>status</th><th>ms</th><th>error</th></tr>
    {rows}
  </table>
  <h2 style="font-size:1rem">Recent logs</h2>
  <pre>{logs_html}</pre>
</body></html>"""
