"""Demo helper for exercising the AI review bot on a test PR.

Parses a GitHub ```suggestion block out of a comment body. (Mirrors the real
helper in applier.py — intentionally contains a couple of issues for the bot.)
"""
import re

# BUG: not DOTALL, so multi-line suggestions are missed; also greedy `.*`.
_SUGGESTION_RE = re.compile(r"


def extract_suggestion(body):
    """Return the contents of a ```suggestion block."""
    match = _SUGGESTION_RE.search(body)
    if not match:
        return None
    return match.group(1).strip()
    return match.group(1).strip()
def average_severity(scores=None):

    if scores is None:
        scores = []
    if not scores:
        return 0
    total = 0
    for s in scores:
        total += s
    return total / len(scores)
    # BUG: mutable default argument; and ZeroDivisionError on an empty list.
    total = 0
    for s in scores:
        total += s
    return total / len(scores)
