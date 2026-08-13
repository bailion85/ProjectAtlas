from core.jobs.executive_brief_worker import _executive_summary


def test_executive_summary_starts_with_plain_english_advisor_context():
    result = _executive_summary(
        {"posture": "Cautious"},
        {
            "tone": "Risk-on",
            "market_summary": "The cross-asset setup is risk-on.",
            "oil": {"value": 82.5, "trend": "Rising"},
            "bonds": [],
            "commodities": [],
            "analyst_notes": [],
        },
        {"trending_stocks": 0},
        {"articles": []},
        {"counts": {"Caution": 1, "Consider less": 1}},
        [{"Ticker": "ABC", "Research label": "Research next", "Discovery score": 70, "Data status": "Live"}],
    )

    assert result.startswith("Here is the simple takeaway:")
    assert "investors are generally feeling optimistic" in result
    assert "does not mean every stock is safe to buy" in result
    assert "higher oil can help energy companies" in result
    assert "2 of your current holdings need extra attention" in result
