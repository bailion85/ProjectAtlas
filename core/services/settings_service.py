from __future__ import annotations

from copy import deepcopy
from typing import Any

from core.services.readiness_service import WEIGHTS as READINESS_WEIGHTS
from core.services.risk_service import WEIGHTS as RISK_WEIGHTS
from core.services.report_repository import ReportRepository


CONFIG_VERSION = 1
DEFAULT_CONFIG = {
    "version": CONFIG_VERSION,
    "profile": "Balanced",
    "committee_preset": "Balanced",
    "technical": {"short_window": 50, "long_window": 200},
    "backtest": {"transaction_cost_bps": 10.0},
    "freshness_days": 7,
    "catalyst_warning_days": 7,
    "risk_weights": dict(RISK_WEIGHTS),
    "readiness_weights": dict(READINESS_WEIGHTS),
    "ranking_weights": {"committee": 45, "inverse_risk": 25, "momentum": 20, "environment": 10},
    "alert_defaults": {"risk_threshold": 65.0, "confidence_change": 10.0, "rank_change": 2,
                       "backtest_floor": 0.0, "stale_days": 7},
}


def profile(name: str) -> dict[str, Any]:
    config = deepcopy(DEFAULT_CONFIG)
    if name == "Growth":
        config.update({"profile": name, "committee_preset": "Growth"})
        config["readiness_weights"] = {
            "Committee conviction": 30, "Risk profile": 15, "Market environment": 10,
            "Technical trend": 20, "Catalyst timing": 10, "Backtest evidence": 10, "Data quality": 5,
        }
    elif name == "Defensive":
        config.update({"profile": name, "committee_preset": "Defensive"})
        config["readiness_weights"] = {
            "Committee conviction": 20, "Risk profile": 30, "Market environment": 15,
            "Technical trend": 10, "Catalyst timing": 15, "Backtest evidence": 5, "Data quality": 5,
        }
    elif name == "Value":
        config.update({"profile": name, "committee_preset": "Value"})
    elif name != "Balanced":
        raise ValueError(f"Unknown settings profile: {name}")
    return config


def load_configuration(repository: ReportRepository) -> dict[str, Any]:
    saved = repository.configuration("active")
    if saved is None:
        return deepcopy(DEFAULT_CONFIG)
    validate_configuration(saved)
    return deepcopy(saved)


def save_configuration(repository: ReportRepository, configuration: dict[str, Any]) -> dict[str, Any]:
    validate_configuration(configuration)
    saved = deepcopy(configuration)
    saved["version"] = CONFIG_VERSION
    repository.save_configuration("active", saved)
    return saved


def validate_configuration(config: dict[str, Any]) -> None:
    if not isinstance(config, dict):
        raise ValueError("Configuration must be a JSON object.")
    if int(config.get("version", CONFIG_VERSION)) != CONFIG_VERSION:
        raise ValueError(f"Unsupported configuration version. Expected version {CONFIG_VERSION}.")
    technical = config.get("technical", {})
    short = int(technical.get("short_window", 0))
    long = int(technical.get("long_window", 0))
    if not 5 <= short < long <= 500:
        raise ValueError("Moving-average periods must satisfy 5 ≤ short < long ≤ 500.")
    cost = float(config.get("backtest", {}).get("transaction_cost_bps", -1))
    if not 0 <= cost <= 500:
        raise ValueError("Backtest transaction cost must be between 0 and 500 basis points.")
    if not 1 <= int(config.get("freshness_days", 0)) <= 365:
        raise ValueError("Freshness must be between 1 and 365 days.")
    if not 1 <= int(config.get("catalyst_warning_days", 0)) <= 90:
        raise ValueError("Catalyst warning must be between 1 and 90 days.")
    _validate_weights("Risk", config.get("risk_weights", {}), set(RISK_WEIGHTS))
    _validate_weights("Entry readiness", config.get("readiness_weights", {}), set(READINESS_WEIGHTS))
    _validate_weights("Watchlist ranking", config.get("ranking_weights", {}), {"committee", "inverse_risk", "momentum", "environment"})


def _validate_weights(label: str, weights: dict[str, Any], expected: set[str]) -> None:
    if set(weights) != expected:
        raise ValueError(f"{label} weights must contain exactly: {', '.join(sorted(expected))}.")
    values = [float(value) for value in weights.values()]
    if any(value < 0 or value > 100 for value in values):
        raise ValueError(f"{label} weights must be between 0 and 100.")
    if abs(sum(values) - 100) > .01:
        raise ValueError(f"{label} weights must total 100%; current total is {sum(values):.2f}%.")
