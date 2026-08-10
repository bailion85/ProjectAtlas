from __future__ import annotations

import os
from abc import ABC, abstractmethod
from datetime import date, datetime, timezone
from typing import Any

from core.providers.market_provider import ProviderError


SERIES = {
    "inflation": {"id": "CPIAUCSL", "label": "Inflation", "unit": "% YoY", "units": "pc1", "max_age": 75},
    "policy_rate": {"id": "FEDFUNDS", "label": "Federal funds rate", "unit": "%", "max_age": 75},
    "treasury_10y": {"id": "DGS10", "label": "10-year Treasury yield", "unit": "%", "max_age": 14},
    "unemployment": {"id": "UNRATE", "label": "Unemployment rate", "unit": "%", "max_age": 75},
    "gdp_growth": {"id": "A191RL1Q225SBEA", "label": "Real GDP growth", "unit": "% annualized", "max_age": 150},
}


class EconomicDataProvider(ABC):
    name: str

    @abstractmethod
    def snapshot(self) -> dict[str, Any]: ...


class DemoEconomicProvider(EconomicDataProvider):
    name = "Demo macro data (not live)"

    def snapshot(self) -> dict[str, Any]:
        today = date.today()
        current_month = today.replace(day=1).isoformat()
        current_quarter = today.replace(month=((today.month - 1) // 3) * 3 + 1, day=1).isoformat()
        values = {
            "inflation": (2.7, current_month),
            "policy_rate": (4.25, current_month),
            "treasury_10y": (4.40, today.isoformat()),
            "unemployment": (4.2, current_month),
            "gdp_growth": (2.4, current_quarter),
        }
        return _build_snapshot(values, self.name)


class FredProvider(EconomicDataProvider):
    name = "Federal Reserve Bank of St. Louis (FRED)"
    base_url = "https://api.stlouisfed.org/fred/series/observations"

    def __init__(self, api_key: str | None = None, timeout: int = 20):
        self.api_key = api_key or os.getenv("FRED_API_KEY")
        if not self.api_key:
            raise ProviderError("FRED_API_KEY is required for live macro data.")
        self.timeout = timeout

    def snapshot(self) -> dict[str, Any]:
        values = {key: self._latest(config) for key, config in SERIES.items()}
        return _build_snapshot(values, self.name)

    def _latest(self, config: dict[str, Any]) -> tuple[float, str]:
        try:
            import requests
        except ImportError as exc:
            raise ProviderError("Install the requests package to use FRED.") from exc
        params = {
            "series_id": config["id"],
            "api_key": self.api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": "12",
        }
        if config.get("units"):
            params["units"] = config["units"]
        try:
            response = requests.get(self.base_url, params=params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise ProviderError(f"FRED request failed: {exc}") from exc
        except ValueError as exc:
            raise ProviderError("FRED returned an invalid response.") from exc
        if payload.get("error_message"):
            raise ProviderError(str(payload["error_message"]))
        for observation in payload.get("observations", []):
            try:
                return float(observation["value"]), observation["date"]
            except (KeyError, TypeError, ValueError):
                continue
        raise ProviderError(f"FRED returned no valid observations for {config['id']}.")


def _build_snapshot(values: dict[str, tuple[float, str]], provider: str) -> dict[str, Any]:
    indicators = {}
    today = date.today()
    for key, (value, observed_on) in values.items():
        config = SERIES[key]
        age_days = (today - date.fromisoformat(observed_on)).days
        indicators[key] = {
            "series_id": config["id"],
            "label": config["label"],
            "value": value,
            "unit": config["unit"],
            "observed_at": observed_on,
            "source": provider,
            "stale": age_days > config["max_age"],
        }
    return {
        "provider": provider,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "indicators": indicators,
    }
