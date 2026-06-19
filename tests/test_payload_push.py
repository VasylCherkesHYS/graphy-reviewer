from app.github.payload import PushCtx

_BASE = {
    "installation": {"id": 99},
    "repository": {"owner": {"login": "acme"}, "name": "widgets", "default_branch": "main"},
    "sender": {"login": "alice", "type": "User"},
    "ref": "refs/heads/main",
    "after": "deadbeefcafe",
}


def _payload(**over):
    p = {k: (dict(v) if isinstance(v, dict) else v) for k, v in _BASE.items()}
    p.update(over)
    return p


def test_default_branch_push():
    ctx = PushCtx.from_payload(_payload())
    assert ctx.is_default_branch
    assert not ctx.deleted
    assert not ctx.sender_is_bot
    assert ctx.owner == "acme" and ctx.repo == "widgets"
    assert ctx.after == "deadbeefcafe"


def test_non_default_branch_push():
    ctx = PushCtx.from_payload(_payload(ref="refs/heads/feature/x"))
    assert not ctx.is_default_branch


def test_branch_deletion():
    ctx = PushCtx.from_payload(_payload(deleted=True))
    assert ctx.deleted


def test_bot_sender_detected():
    ctx = PushCtx.from_payload(_payload(sender={"login": "reviewer-bot[bot]", "type": "Bot"}))
    assert ctx.sender_is_bot
