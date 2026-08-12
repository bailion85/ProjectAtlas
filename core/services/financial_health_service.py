from __future__ import annotations

from typing import Any


TAGS = {
    "Revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"),
    "Net income": ("NetIncomeLoss", "ProfitLoss"),
    "Operating income": ("OperatingIncomeLoss",),
    "Operating cash flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "Capital spending": ("PaymentsToAcquirePropertyPlantAndEquipment",),
    "Assets": ("Assets",), "Liabilities": ("Liabilities",),
    "Equity": ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
    "Shares": ("CommonStockSharesOutstanding", "EntityCommonStockSharesOutstanding"),
}


def analyze_financial_health(snapshot: dict[str, Any]) -> dict[str, Any]:
    us_gaap = snapshot.get("facts", {}).get("us-gaap", {})
    series = {label: _annual_series(us_gaap, tags) for label, tags in TAGS.items()}
    quarterly_series = {label: _quarterly_series(us_gaap, tags) for label, tags in TAGS.items()}
    years = sorted({year for values in series.values() for year in values})[-5:]
    if len(years) < 2:
        raise ValueError("SEC data does not contain at least two comparable annual periods for this company.")
    rows = []
    for year in years:
        row = {"Fiscal year": year}
        for label, values in series.items():
            row[label] = values.get(year)
        if row["Operating cash flow"] is not None and row["Capital spending"] is not None:
            row["Free cash flow"] = row["Operating cash flow"] - row["Capital spending"]
        else:
            row["Free cash flow"] = None
        row["Net margin"] = _ratio(row["Net income"], row["Revenue"])
        row["Operating margin"] = _ratio(row["Operating income"], row["Revenue"])
        rows.append(row)
    latest, previous = rows[-1], rows[-2]
    signals = []
    score_parts = []
    for label, positive in (("Revenue", True), ("Net income", True), ("Free cash flow", True), ("Shares", False), ("Liabilities", False)):
        change = _change(latest.get(label), previous.get(label))
        if change is None:
            continue
        favorable = change >= 0 if positive else change <= 0
        score_parts.append(75 if favorable else 25)
        signals.append({"Factor": label, "Direction": "Improving" if favorable else "Deteriorating", "Change": change})
    score = round(sum(score_parts) / len(score_parts)) if score_parts else 50
    posture = "Strong" if score >= 70 else "Stable" if score >= 50 else "Weakening"
    available = sum(bool(values) for values in series.values())
    quarters = sorted({period for values in quarterly_series.values() for period in values})[-8:]
    quarterly_rows = []
    for period in quarters:
        row = {"Quarter": period}
        for label, values in quarterly_series.items():
            row[label] = values.get(period)
        if row["Operating cash flow"] is not None and row["Capital spending"] is not None:
            row["Free cash flow"] = row["Operating cash flow"] - row["Capital spending"]
        else:
            row["Free cash flow"] = None
        row["Net margin"] = _ratio(row["Net income"], row["Revenue"])
        row["Operating margin"] = _ratio(row["Operating income"], row["Revenue"])
        quarterly_rows.append(row)
    latest_filing = _latest_filing(us_gaap)
    return {
        "ticker": snapshot["ticker"], "company": snapshot["company"], "cik": snapshot["cik"],
        "provider": snapshot["provider"], "retrieved_at": snapshot["retrieved_at"],
        "cache_status": snapshot.get("cache_status"), "score": score, "posture": posture,
        "rows": rows, "quarterly_rows": quarterly_rows, "signals": signals,
        "coverage": round(available / len(TAGS) * 100), "latest_filing": latest_filing,
        "summary": f"{snapshot['ticker']} financial health is {posture.lower()} based on {len(years)} annual SEC periods.",
        "disclosure": "SEC XBRL tags vary by issuer. Missing values are not treated as zero, and this historical screen is not investment advice.",
    }


def _annual_series(facts: dict[str, Any], tags: tuple[str, ...]) -> dict[int, float]:
    for tag in tags:
        fact = facts.get(tag, {})
        units = fact.get("units", {})
        candidates = units.get("USD") or units.get("shares") or units.get("pure") or []
        annual = {}
        for item in candidates:
            if item.get("form") not in {"10-K", "10-K/A"} or item.get("fy") is None:
                continue
            try:
                year, value = int(item["fy"]), float(item["val"])
            except (KeyError, TypeError, ValueError):
                continue
            filed = str(item.get("filed", ""))
            if year not in annual or filed >= annual[year][0]:
                annual[year] = (filed, value)
        if annual:
            return {year: value for year, (_, value) in annual.items()}
    return {}


def _quarterly_series(facts: dict[str, Any], tags: tuple[str, ...]) -> dict[str, float]:
    for tag in tags:
        fact = facts.get(tag, {})
        units = fact.get("units", {})
        candidates = units.get("USD") or units.get("shares") or units.get("pure") or []
        quarterly: dict[str, tuple[str, float]] = {}
        for item in candidates:
            frame = str(item.get("frame", ""))
            if item.get("form") not in {"10-Q", "10-Q/A"} or "Q" not in frame:
                continue
            period = frame.rstrip("I")
            if not period.startswith("CY") or len(period) < 8:
                continue
            try:
                value = float(item["val"])
            except (KeyError, TypeError, ValueError):
                continue
            filed = str(item.get("filed", ""))
            if period not in quarterly or filed >= quarterly[period][0]:
                quarterly[period] = (filed, value)
        if quarterly:
            return {period: value for period, (_, value) in quarterly.items()}
    return {}


def _latest_filing(facts: dict[str, Any]) -> dict[str, Any] | None:
    filings = []
    for fact in facts.values():
        for candidates in fact.get("units", {}).values():
            for item in candidates:
                if item.get("form") not in {"10-K", "10-K/A", "10-Q", "10-Q/A"}:
                    continue
                if not item.get("filed") or not item.get("accn"):
                    continue
                filings.append({
                    "filed": str(item["filed"]), "form": str(item["form"]),
                    "accession": str(item["accn"]), "fiscal_year": item.get("fy"),
                    "fiscal_period": item.get("fp"),
                })
    return max(filings, key=lambda item: (item["filed"], item["accession"])) if filings else None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    return round(numerator / denominator * 100, 1) if numerator is not None and denominator else None


def _change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return round((current / previous - 1) * 100, 1)
