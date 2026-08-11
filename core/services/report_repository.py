from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from core.models.research import AgentAssessment, Evidence, ResearchReport


class ReportRepository:
    def __init__(self, path: str | Path = "data/atlas.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS watchlist (ticker TEXT PRIMARY KEY, added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            db.execute("CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY, ticker TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS comparisons (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS alert_rules (ticker TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY, ticker TEXT NOT NULL, alert_type TEXT NOT NULL, "
                "severity TEXT NOT NULL, title TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "fingerprint TEXT NOT NULL UNIQUE, is_read INTEGER NOT NULL DEFAULT 0, payload TEXT NOT NULL DEFAULT '{}')"
            )
            db.execute("CREATE TABLE IF NOT EXISTS configurations (name TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS portfolio_positions (ticker TEXT PRIMARY KEY, allocation REAL NOT NULL, "
                "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS scheduler_runs (id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, "
                "completed_at TEXT, status TEXT NOT NULL, scope TEXT NOT NULL, requested INTEGER NOT NULL DEFAULT 0, "
                "analyzed INTEGER NOT NULL DEFAULT 0, alerts_created INTEGER NOT NULL DEFAULT 0, "
                "errors TEXT NOT NULL DEFAULT '[]')"
            )

    def watchlist(self) -> list[str]:
        with self._connect() as db:
            return [row["ticker"] for row in db.execute("SELECT ticker FROM watchlist ORDER BY ticker")]

    def add_ticker(self, ticker: str) -> None:
        ticker = _normalize_ticker(ticker)
        with self._connect() as db:
            db.execute("INSERT OR IGNORE INTO watchlist(ticker) VALUES (?)", (ticker,))

    def remove_ticker(self, ticker: str) -> None:
        ticker = _normalize_ticker(ticker)
        with self._connect() as db:
            db.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker,))

    def portfolio_positions(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT ticker, allocation FROM portfolio_positions ORDER BY allocation DESC, ticker"
            )]

    def save_portfolio_positions(self, positions: list[dict[str, Any]]) -> None:
        normalized = []
        for position in positions:
            ticker = _normalize_ticker(str(position.get("ticker") or position.get("Ticker") or ""))
            allocation = float(position.get("allocation", position.get("Allocation", 0)) or 0)
            if allocation < 0 or allocation > 100:
                raise ValueError(f"{ticker} allocation must be between 0% and 100%.")
            if allocation > 0:
                normalized.append((ticker, allocation))
        if len({ticker for ticker, _ in normalized}) != len(normalized):
            raise ValueError("Each portfolio ticker must appear only once.")
        with self._connect() as db:
            db.execute("DELETE FROM portfolio_positions")
            db.executemany(
                "INSERT INTO portfolio_positions(ticker, allocation) VALUES (?, ?)", normalized
            )

    def save(self, report: ResearchReport) -> int:
        with self._connect() as db:
            cursor = db.execute("INSERT INTO reports(ticker, created_at, payload) VALUES (?, ?, ?)", (report.ticker, report.created_at, json.dumps(report.to_dict())))
            return int(cursor.lastrowid)

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT id, ticker, created_at FROM reports ORDER BY id DESC LIMIT ?", (limit,))]

    def report_tickers(self) -> list[str]:
        with self._connect() as db:
            return [row["ticker"] for row in db.execute("SELECT DISTINCT ticker FROM reports ORDER BY ticker")]

    def get(self, report_id: int) -> ResearchReport | None:
        with self._connect() as db:
            row = db.execute("SELECT payload FROM reports WHERE id = ?", (report_id,)).fetchone()
        if not row:
            return None
        data = json.loads(row["payload"])
        data["assessments"] = [AgentAssessment(**{**a, "evidence": [Evidence(**e) for e in a["evidence"]]}) for a in data["assessments"]]
        data["report_id"] = report_id
        return ResearchReport(**data)

    def latest_reports(self, tickers: list[str]) -> dict[str, ResearchReport]:
        normalized = list(dict.fromkeys(_normalize_ticker(ticker) for ticker in tickers))
        if not normalized:
            return {}
        placeholders = ",".join("?" for _ in normalized)
        query = (
            "SELECT r.id FROM reports r "
            "JOIN (SELECT ticker, MAX(id) AS latest_id FROM reports "
            f"WHERE ticker IN ({placeholders}) GROUP BY ticker) latest ON r.id = latest.latest_id"
        )
        with self._connect() as db:
            ids = [int(row["id"]) for row in db.execute(query, normalized)]
        reports = [self.get(report_id) for report_id in ids]
        return {report.ticker: report for report in reports if report is not None}

    def recent_reports(self, ticker: str, limit: int = 2) -> list[ResearchReport]:
        symbol = _normalize_ticker(ticker)
        with self._connect() as db:
            ids = [int(row["id"]) for row in db.execute(
                "SELECT id FROM reports WHERE ticker = ? ORDER BY id DESC LIMIT ?", (symbol, max(1, limit))
            )]
        return [report for report_id in ids if (report := self.get(report_id)) is not None]

    def save_alert_rule(self, ticker: str, rule: dict[str, Any]) -> None:
        symbol = _normalize_ticker(ticker)
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO alert_rules(ticker, payload, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                (symbol, json.dumps(rule)),
            )

    def alert_rule(self, ticker: str) -> dict[str, Any] | None:
        symbol = _normalize_ticker(ticker)
        with self._connect() as db:
            row = db.execute("SELECT payload FROM alert_rules WHERE ticker = ?", (symbol,)).fetchone()
        return json.loads(row["payload"]) if row else None

    def add_alert(self, alert: dict[str, Any]) -> bool:
        with self._connect() as db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO alerts(ticker, alert_type, severity, title, message, fingerprint, payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (alert["ticker"], alert["alert_type"], alert["severity"], alert["title"], alert["message"],
                 alert["fingerprint"], json.dumps(alert.get("payload", {}))),
            )
            return cursor.rowcount == 1

    def alerts(self, limit: int = 100, unread_only: bool = False) -> list[dict[str, Any]]:
        where = "WHERE is_read = 0" if unread_only else ""
        with self._connect() as db:
            rows = db.execute(
                f"SELECT id, ticker, alert_type, severity, title, message, created_at, is_read, payload "
                f"FROM alerts {where} ORDER BY id DESC LIMIT ?", (max(1, limit),)
            ).fetchall()
        return [{**dict(row), "is_read": bool(row["is_read"]), "payload": json.loads(row["payload"])} for row in rows]

    def unread_alert_count(self) -> int:
        with self._connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM alerts WHERE is_read = 0").fetchone()[0])

    def mark_alerts_read(self) -> None:
        with self._connect() as db:
            db.execute("UPDATE alerts SET is_read = 1 WHERE is_read = 0")

    def save_configuration(self, name: str, configuration: dict[str, Any]) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO configurations(name, payload, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                (name, json.dumps(configuration)),
            )

    def configuration(self, name: str = "active") -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT payload FROM configurations WHERE name = ?", (name,)).fetchone()
        return json.loads(row["payload"]) if row else None

    def start_scheduler_run(self, started_at: str, scope: str, requested: int) -> int:
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO scheduler_runs(started_at, status, scope, requested) VALUES (?, 'Running', ?, ?)",
                (started_at, scope, requested),
            )
            return int(cursor.lastrowid)

    def finish_scheduler_run(
        self, run_id: int, completed_at: str, status: str, analyzed: int,
        alerts_created: int, errors: list[str],
    ) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE scheduler_runs SET completed_at = ?, status = ?, analyzed = ?, alerts_created = ?, errors = ? "
                "WHERE id = ?",
                (completed_at, status, analyzed, alerts_created, json.dumps(errors), run_id),
            )

    def scheduler_runs(self, limit: int = 25) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, started_at, completed_at, status, scope, requested, analyzed, alerts_created, errors "
                "FROM scheduler_runs ORDER BY id DESC LIMIT ?", (max(1, limit),),
            ).fetchall()
        return [{**dict(row), "errors": json.loads(row["errors"])} for row in rows]

    def save_comparison(self, comparison: dict[str, Any]) -> int:
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO comparisons(created_at, payload) VALUES (?, ?)",
                (comparison["created_at"], json.dumps(comparison)),
            )
            return int(cursor.lastrowid)

    def comparison_history(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT id, created_at, payload FROM comparisons ORDER BY id DESC LIMIT ?", (limit,)
            )]

    def get_comparison(self, comparison_id: int) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT payload FROM comparisons WHERE id = ?", (comparison_id,)).fetchone()
        return json.loads(row["payload"]) if row else None


def _normalize_ticker(ticker: str) -> str:
    normalized = ticker.strip().upper()
    if not normalized:
        raise ValueError("Ticker cannot be empty.")
    if len(normalized) > 15 or not all(character.isalnum() or character in ".-" for character in normalized):
        raise ValueError("Ticker contains unsupported characters.")
    return normalized
