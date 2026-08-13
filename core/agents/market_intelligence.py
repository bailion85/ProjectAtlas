from __future__ import annotations

from core.models.research import AgentAssessment, Evidence
from core.services.market_intelligence_service import build_market_intelligence


MARKET_INTELLIGENCE_AGENT_VERSION = 1


class MarketIntelligenceAgent:
    name = "Market Intelligence"

    def __init__(self, repository):
        self.repository = repository

    def assess(self, ticker: str, sector: str | None = None) -> AgentAssessment:
        state = self.repository.configuration("market_intelligence") or {}
        result = build_market_intelligence(
            ticker, state.get("sources", []), state.get("commentary", []), sector=sector,
        )
        if not result["items"]:
            return AgentAssessment(
                self.name, "neutral", 15,
                "No current saved Market Intelligence evidence matched this company; the agent abstains.",
                [],
            )
        vote = result["vote"].lower()
        confidence = int(result["confidence"])
        thesis = result["summary"]
        if result["analysts"] < 2:
            vote = "neutral"
            confidence = min(confidence, 35)
            thesis += " The agent abstains from a directional vote because independent-source confirmation is missing."
        evidence = [Evidence(
            label=f"{row['Analyst']} · {row['Stance']} · {row['Argument']}",
            value=str(row["Commentary"]), source=str(row.get("Source URL") or row["Platform"]),
            observed_at=str(row.get("Age (days)", "Current")),
        ) for row in result["rows"][:5]]
        return AgentAssessment(self.name, vote, confidence, thesis, evidence)
