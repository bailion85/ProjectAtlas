from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


Vote = Literal["bullish", "neutral", "bearish"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Evidence:
    label: str
    value: str
    source: str
    observed_at: str


@dataclass(frozen=True)
class AgentAssessment:
    strategy: str
    vote: Vote
    confidence: int
    thesis: str
    evidence: list[Evidence] = field(default_factory=list)


@dataclass(frozen=True)
class ResearchReport:
    ticker: str
    company: str
    created_at: str
    data_as_of: str
    executive_summary: str
    bull_case: list[str]
    bear_case: list[str]
    risks: list[str]
    catalysts: list[str]
    assessments: list[AgentAssessment]
    committee_vote: Vote
    committee_confidence: int
    provider: str
    performance: dict[str, Any] = field(default_factory=dict)
    performance_history: list[dict[str, Any]] = field(default_factory=list)
    report_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
