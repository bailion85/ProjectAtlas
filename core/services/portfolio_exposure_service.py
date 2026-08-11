from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.models.research import ResearchReport


PORTFOLIO_EXPOSURE_SERVICE_VERSION = 1


def analyze_portfolio_exposure(
    positions: list[dict[str, Any]],
    reports: dict[str, ResearchReport],
    freshness_days: int = 7,
) -> dict[str, Any]:
    cleaned = _clean_positions(positions)
    total_allocation = sum(item["allocation"] for item in cleaned)
    if not cleaned:
        raise ValueError("Add at least one portfolio holding.")
    if total_allocation <= 0:
        raise ValueError("Portfolio allocations must total more than 0%.")

    rows = []
    missing = []
    sectors: dict[str, float] = {}
    for position in cleaned:
        ticker = position["ticker"]
        report = reports.get(ticker)
        if report is None:
            missing.append(ticker)
            continue
        normalized = position["allocation"] / total_allocation * 100
        sector = str(report.company_metrics.get("sector") or "Unknown")
        sectors[sector] = sectors.get(sector, 0) + normalized
        catalyst = report.catalyst_calendar or {}
        next_event = catalyst.get("next_event") or {}
        rows.append({
            "Ticker": ticker,
            "Company": report.company,
            "Allocation": round(position["allocation"], 2),
            "Portfolio weight": round(normalized, 2),
            "Sector": sector,
            "Committee score": round(float(report.committee_score), 1),
            "Vote": report.committee_vote.title(),
            "Risk score": round(float(report.risk.get("score", 50)), 1),
            "Risk level": report.risk.get("severity", "Unavailable"),
            "Entry readiness": round(float(report.entry_readiness.get("score", 50)), 1),
            "Entry posture": report.entry_readiness.get("posture", "Unavailable"),
            "Beta": _number(report.company_metrics.get("beta")),
            "Catalyst readiness": catalyst.get("readiness", "Unavailable"),
            "Next catalyst": next_event.get("title", "Unavailable"),
            "Days to catalyst": next_event.get("days_until"),
            "Freshness": "Stale" if _age_days(report.created_at) > freshness_days else "Current",
            "report_id": report.report_id,
        })

    covered_weight = sum(row["Portfolio weight"] for row in rows)
    weighted_risk = _weighted(rows, "Risk score")
    weighted_readiness = _weighted(rows, "Entry readiness")
    weighted_committee = _weighted(rows, "Committee score")
    weighted_beta = _weighted(rows, "Beta", skip_none=True)
    concentration = sum((row["Portfolio weight"] / 100) ** 2 for row in rows)
    effective_positions = 1 / concentration if concentration else 0
    warnings = _warnings(rows, sectors, missing, total_allocation)
    posture = _posture(weighted_risk, weighted_readiness, warnings, covered_weight)
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "total_allocation": round(total_allocation, 2),
        "covered_weight": round(covered_weight, 1),
        "weighted_risk": weighted_risk,
        "weighted_readiness": weighted_readiness,
        "weighted_committee": weighted_committee,
        "weighted_beta": weighted_beta,
        "concentration_index": round(concentration * 100, 1),
        "effective_positions": round(effective_positions, 1),
        "posture": posture,
        "rows": rows,
        "sector_exposure": [
            {"Sector": sector, "Allocation": round(weight, 1)}
            for sector, weight in sorted(sectors.items(), key=lambda item: item[1], reverse=True)
        ],
        "warnings": warnings,
        "missing": missing,
        "disclosure": "Portfolio exposure is an analysis aid, not investment advice or a recommendation to trade or rebalance.",
    }


def _clean_positions(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    combined: dict[str, float] = {}
    for item in positions:
        ticker = str(item.get("ticker") or item.get("Ticker") or "").strip().upper()
        raw_allocation = item.get("allocation", item.get("Allocation", 0))
        if not ticker and (raw_allocation is None or float(raw_allocation or 0) == 0):
            continue
        if not ticker or len(ticker) > 15 or not all(character.isalnum() or character in ".-" for character in ticker):
            raise ValueError("Each portfolio row needs a valid ticker.")
        allocation = float(raw_allocation or 0)
        if allocation < 0 or allocation > 100:
            raise ValueError(f"{ticker} allocation must be between 0% and 100%.")
        combined[ticker] = combined.get(ticker, 0) + allocation
    return [{"ticker": ticker, "allocation": allocation} for ticker, allocation in combined.items() if allocation > 0]


def _weighted(rows: list[dict[str, Any]], field: str, skip_none: bool = False) -> float | None:
    available = [row for row in rows if not skip_none or row[field] is not None]
    weight = sum(row["Portfolio weight"] for row in available)
    if not available or weight <= 0:
        return None
    return round(sum(float(row[field]) * row["Portfolio weight"] for row in available) / weight, 1)


def _warnings(rows: list[dict[str, Any]], sectors: dict[str, float], missing: list[str], total: float) -> list[dict[str, str]]:
    warnings = []
    if abs(total - 100) > .05:
        warnings.append({"severity": "Moderate", "title": "Allocation total", "message": f"Allocations total {total:.1f}%, not 100%. Atlas normalized the exposure calculations."})
    for row in rows:
        if row["Portfolio weight"] >= 35:
            warnings.append({"severity": "High", "title": f"{row['Ticker']} concentration", "message": f"{row['Ticker']} represents {row['Portfolio weight']:.1f}% of covered exposure."})
        if row["Risk score"] >= 70:
            warnings.append({"severity": "High", "title": f"{row['Ticker']} risk", "message": f"Risk is {row['Risk score']:.1f}/100 and {row['Risk level'].lower()}."})
        days = row["Days to catalyst"]
        if days is not None and int(days) <= 7:
            warnings.append({"severity": "High", "title": f"{row['Ticker']} catalyst", "message": f"{row['Next catalyst']} is due in {days} day(s)."})
        if row["Freshness"] == "Stale":
            warnings.append({"severity": "Moderate", "title": f"{row['Ticker']} research is stale", "message": "Refresh this holding before relying on the portfolio view."})
    for sector, weight in sectors.items():
        if weight >= 50:
            warnings.append({"severity": "High", "title": f"{sector} concentration", "message": f"{weight:.1f}% of covered exposure is in {sector}."})
    if missing:
        warnings.append({"severity": "Moderate", "title": "Missing research", "message": "No saved Atlas report exists for: " + ", ".join(missing) + "."})
    return warnings


def _posture(risk: float | None, readiness: float | None, warnings: list[dict[str, str]], coverage: float) -> str:
    if coverage < 70:
        return "Insufficient coverage"
    if any(item["severity"] == "High" for item in warnings) or (risk is not None and risk >= 65):
        return "Elevated exposure"
    if readiness is not None and readiness >= 65 and risk is not None and risk < 50:
        return "Constructive"
    return "Balanced watch"


def _number(value: Any) -> float | None:
    try:
        return round(float(value), 2) if value is not None else None
    except (TypeError, ValueError):
        return None


def _age_days(value: str) -> float:
    observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - observed).total_seconds() / 86400)
