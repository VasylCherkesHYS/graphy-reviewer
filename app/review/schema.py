from typing import Literal

from pydantic import BaseModel


class Finding(BaseModel):
    path: str
    line: int
    severity: Literal["critical", "major", "minor", "nit"]
    title: str
    body: str


class ReviewResult(BaseModel):
    summary: str
    graph_used: bool
    graph_evidence: str
    findings: list[Finding]
