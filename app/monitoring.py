"""In-memory observability: webhook-delivery tracking + a ring buffer of log lines.

Everything lives in process memory (no DB). It is reset on restart and is meant
for "is the app healthy / what did the last requests do" visibility, exposed via
the /stats, /events, /logs and /dashboard endpoints in app.main.
"""
import logging
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from threading import Lock

_MAX_DELIVERIES = 200
_MAX_LOG_LINES = 500


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


@dataclass
class DeliveryRecord:
    delivery_id: str
    event: str
    action: str | None = None
    repo: str | None = None
    pr: int | None = None
    status: str = "processing"  # processing | ok | error | skipped
    error: str | None = None
    received_at: float = field(default_factory=time.time)
    duration_ms: float | None = None

    def as_dict(self) -> dict:
        d = asdict(self)
        d["received_at"] = _iso(self.received_at)
        return d


class Monitor:
    """Tracks webhook deliveries and aggregate counters. Thread-safe."""

    def __init__(self, maxlen: int = _MAX_DELIVERIES) -> None:
        self._deliveries: deque[DeliveryRecord] = deque(maxlen=maxlen)
        self._by_id: dict[str, DeliveryRecord] = {}
        self._lock = Lock()
        self.started_at = time.time()
        self.counters: dict[str, int] = {
            "received": 0, "ok": 0, "error": 0, "skipped": 0,
        }

    def start(
        self,
        delivery_id: str,
        event: str,
        action: str | None = None,
        repo: str | None = None,
        pr: int | None = None,
    ) -> None:
        rec = DeliveryRecord(
            delivery_id=delivery_id or "(none)",
            event=event,
            action=action,
            repo=repo,
            pr=pr,
        )
        with self._lock:
            self.counters["received"] += 1
            self._deliveries.appendleft(rec)
            if delivery_id:
                self._by_id[delivery_id] = rec

    def finish(self, delivery_id: str, status: str, error: str | None = None) -> None:
        with self._lock:
            rec = self._by_id.get(delivery_id)
            if rec is None:
                return
            rec.status = status
            rec.error = error
            rec.duration_ms = round((time.time() - rec.received_at) * 1000, 1)
            if status in self.counters:
                self.counters[status] += 1

    def snapshot_stats(self) -> dict:
        with self._lock:
            uptime = time.time() - self.started_at
            recent = list(self._deliveries)
        last_error = next(
            (r.as_dict() for r in recent if r.status == "error"), None
        )
        return {
            "status": "ok",
            "started_at": _iso(self.started_at),
            "uptime_seconds": round(uptime, 1),
            "counters": dict(self.counters),
            "tracked_deliveries": len(recent),
            "last_error": last_error,
        }

    def recent(self, limit: int = 50, status: str | None = None) -> list[dict]:
        with self._lock:
            recent = list(self._deliveries)
        if status:
            recent = [r for r in recent if r.status == status]
        return [r.as_dict() for r in recent[:limit]]


class RingBufferLogHandler(logging.Handler):
    """Keeps the most recent formatted log lines in memory for the /logs endpoint."""

    def __init__(self, maxlen: int = _MAX_LOG_LINES) -> None:
        super().__init__()
        # Store (levelname, formatted_line) so level filtering is exact and does
        # not depend on the formatter layout.
        self._lines: deque[tuple[str, str]] = deque(maxlen=maxlen)
        self._buf_lock = Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:
            return
        with self._buf_lock:
            self._lines.appendleft((record.levelname, line))

    def lines(self, limit: int = 100, level: str | None = None) -> list[str]:
        with self._buf_lock:
            out = list(self._lines)
        if level:
            want = level.upper()
            out = [item for item in out if item[0] == want]
        return [line for _, line in out[:limit]]


# Process-wide singletons.
monitor = Monitor()
log_buffer = RingBufferLogHandler()


def summarize_payload(event: str, payload: dict) -> tuple[str | None, str | None, int | None]:
    """Best-effort (action, repo_full_name, pr_number) for a webhook payload."""
    action = payload.get("action")
    repo = (payload.get("repository") or {}).get("full_name")
    pr = None
    if "pull_request" in payload and isinstance(payload["pull_request"], dict):
        pr = payload["pull_request"].get("number")
    elif "issue" in payload and isinstance(payload["issue"], dict):
        pr = payload["issue"].get("number")
    elif event == "push" and payload.get("ref"):
        # No action field on push events; surface the ref instead.
        action = f"push {payload['ref']}"
    return action, repo, pr
