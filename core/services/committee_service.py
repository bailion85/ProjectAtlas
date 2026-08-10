from __future__ import annotations

from typing import Any

from core.models.research import AgentAssessment, Vote


STRATEGIES = ("Value", "GARP", "Innovation", "Macro", "Quant", "Risk")
PRESETS = {
    "Balanced": {strategy: 1 for strategy in STRATEGIES},
    "Growth": {"Value": 10, "GARP": 25, "Innovation": 25, "Macro": 10, "Quant": 20, "Risk": 10},
    "Value": {"Value": 35, "GARP": 20, "Innovation": 5, "Macro": 10, "Quant": 10, "Risk": 20},
    "Defensive": {"Value": 20, "GARP": 10, "Innovation": 5, "Macro": 20, "Quant": 10, "Risk": 35},
}


def normalize_weights(weights: dict[str, float] | None = None) -> dict[str, float]:
    supplied = weights or PRESETS["Balanced"]
    unknown = set(supplied) - set(STRATEGIES)
    if unknown:
        raise ValueError("Unknown strategies: " + ", ".join(sorted(unknown)))
    normalized_input = {}
    for strategy in STRATEGIES:
        try:
            value = float(supplied.get(strategy, 0))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Weight for {strategy} must be numeric.") from exc
        if value < 0:
            raise ValueError(f"Weight for {strategy} cannot be negative.")
        normalized_input[strategy] = value
    total = sum(normalized_input.values())
    if total <= 0:
        raise ValueError("At least one strategy weight must be greater than zero.")
    normalized = {}
    for strategy in STRATEGIES[:-1]:
        normalized[strategy] = round(normalized_input[strategy] / total * 100, 4)
    normalized[STRATEGIES[-1]] = round(100 - sum(normalized.values()), 4)
    return normalized


class CommitteeService:
    def decide(
        self,
        assessments: list[AgentAssessment],
        strategy_weights: dict[str, float] | None = None,
    ) -> tuple[Vote, int, list[dict[str, Any]]]:
        weights = normalize_weights(strategy_weights)
        directions = {"bullish": 1, "neutral": 0, "bearish": -1}
        contributions = []
        numerator = 0.0
        denominator = 0.0
        for assessment in assessments:
            weight = weights[assessment.strategy]
            signal = directions[assessment.vote] * assessment.confidence * weight / 100
            numerator += signal
            denominator += assessment.confidence * weight / 100
            contributions.append({
                "strategy": assessment.strategy,
                "weight": weight,
                "vote": assessment.vote,
                "confidence": assessment.confidence,
                "weighted_signal": round(signal, 2),
            })
        normalized_signal = numerator / denominator if denominator else 0
        vote: Vote = "bullish" if normalized_signal >= .2 else "bearish" if normalized_signal <= -.2 else "neutral"
        confidence = round(50 + abs(normalized_signal) * 45)
        return vote, confidence, contributions


def score_contributions(contributions: list[dict[str, Any]]) -> float:
    numerator = sum(item["weighted_signal"] for item in contributions)
    denominator = sum(item["confidence"] * item["weight"] / 100 for item in contributions)
    normalized_signal = numerator / denominator if denominator else 0
    return round((normalized_signal + 1) * 50, 2)
