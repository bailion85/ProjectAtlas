from core.services.market_pulse_service import build_market_pulse


class MarketStub:
    name = "Live quotes"

    def market_dashboard(self, tickers):
        changes = {"DIA": 0.8, "SPY": 1.0, "QQQ": 1.2, "IWM": -0.1, "TLT": -0.3, "IEF": 0.1, "SHY": 0.05, "LQD": 0.2, "HYG": 0.1, "CL=F": 1.5, "GC=F": 0.2, "SI=F": 0.4, "HG=F": 0.3, "UUP": -0.2}
        return {
            "provider": "Tiingo IEX",
            "quotes": [
                {"ticker": ticker, "price": 100 + index, "change_percent": changes[ticker],
                 "observed_at": "2026-08-13T14:30:00Z"}
                for index, ticker in enumerate(tickers)
            ],
        }


class MacroStub:
    name = "FRED"

    def snapshot(self):
        def indicator(label, value, unit, change, trend, series):
            return {"label": label, "value": value, "unit": unit, "change_percent": change,
                    "trend": trend, "observed_at": "2026-08-12", "source": "FRED",
                    "series_id": series, "stale": False}
        return {
            "provider": "FRED", "retrieved_at": "2026-08-13T14:00:00Z",
            "indicators": {
                "oil_wti": indicator("WTI crude oil", 82.5, "$/barrel", 1.5, "Rising", "DCOILWTICO"),
                "treasury_10y": indicator("10-year Treasury yield", 4.2, "%", -0.4, "Falling", "DGS10"),
                "policy_rate": indicator("Federal funds rate", 4.25, "%", 0, "Flat", "FEDFUNDS"),
                "inflation": indicator("Inflation", 2.7, "% YoY", -1.0, "Falling", "CPIAUCSL"),
            },
        }


def test_market_pulse_combines_batched_quotes_and_macro_trends():
    pulse = build_market_pulse(MarketStub(), MacroStub())

    assert pulse["status"] == "Ready"
    assert pulse["tone"] == "Risk-on"
    assert len(pulse["quotes"]) == 14
    assert len(pulse["bonds"]) == 5
    assert {row["ticker"] for row in pulse["commodities"]} == {"CL=F", "GC=F", "SI=F", "HG=F"}
    assert pulse["analyst_notes"]
    assert pulse["oil"]["value"] == 82.5
    assert pulse["oil"]["trend"] == "Rising"
    assert pulse["rates"]["treasury_10y"]["trend"] == "Falling"
    assert "ETF proxies" in pulse["disclosure"]