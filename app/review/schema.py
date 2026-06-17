from typing import Literal

from pydantic import BaseModel


class Finding(BaseModel):
    path: str
    line: int  # line in the NEW file (right side of the diff)
    severity: Literal["critical", "major", "minor", "nit"]
    title: str
    body: str
    # Optional concrete fix rendered as a GitHub ```suggestion``` block.
    start_line: int | None = None  # first line of the range, if the fix spans several lines
    suggestion: str | None = None  # full replacement code for lines start_line..line


class ReviewResult(BaseModel):
    summary: str
    graph_used: bool
    graph_evidence: str
    findings: list[Finding]


class Edit(BaseModel):
    """A single exact-string replacement inside one file."""

    old: str  # exact text to find (must occur exactly once)
    new: str  # replacement text


class FixEdit(BaseModel):
    """LLM output describing how to apply a suggested fix to one file."""

    file: str
    edits: list[Edit]
    commit_message: str
    note: str = ""  # short human note, posted back into the thread
    applicable: bool = True  # False when the suggestion can't be auto-applied


class ApplyOutcome(BaseModel):
    """Result of attempting to apply one finding to the working tree."""

    applied: bool
    sha: str | None = None
    note: str = ""
