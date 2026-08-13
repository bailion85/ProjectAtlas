from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Iterator

from core.models.research import AgentAssessment, Evidence, ResearchReport

REPORT_REPOSITORY_VERSION = 2


class ReportRepository:
    def __init__(self, path: str | Path = "data/atlas.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self.expire_invalid_catalyst_alerts()

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
                "fingerprint TEXT NOT NULL UNIQUE, is_read INTEGER NOT NULL DEFAULT 0, expired INTEGER NOT NULL DEFAULT 0, "
                "payload TEXT NOT NULL DEFAULT '{}')"
            )
            alert_columns = {row[1] for row in db.execute("PRAGMA table_info(alerts)")}
            if "expired" not in alert_columns:
                db.execute("ALTER TABLE alerts ADD COLUMN expired INTEGER NOT NULL DEFAULT 0")
            db.execute("CREATE TABLE IF NOT EXISTS configurations (name TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS portfolio_positions (ticker TEXT PRIMARY KEY, allocation REAL NOT NULL, "
                "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS portfolio_holdings (ticker TEXT PRIMARY KEY, "
                "added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            db.execute(
                "INSERT OR IGNORE INTO portfolio_holdings(ticker) SELECT ticker FROM portfolio_positions"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS scheduler_runs (id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, "
                "completed_at TEXT, status TEXT NOT NULL, scope TEXT NOT NULL, requested INTEGER NOT NULL DEFAULT 0, "
                "analyzed INTEGER NOT NULL DEFAULT 0, alerts_created INTEGER NOT NULL DEFAULT 0, "
                "errors TEXT NOT NULL DEFAULT '[]')"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS theses (id INTEGER PRIMARY KEY, ticker TEXT NOT NULL, "
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, payload TEXT NOT NULL)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_theses_ticker_id ON theses(ticker, id DESC)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS valuations (id INTEGER PRIMARY KEY, ticker TEXT NOT NULL, "
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, payload TEXT NOT NULL)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_valuations_ticker_id ON valuations(ticker, id DESC)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS financial_health (id INTEGER PRIMARY KEY, ticker TEXT NOT NULL, "
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, payload TEXT NOT NULL)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_financial_health_ticker_id ON financial_health(ticker, id DESC)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS sec_monitor_checks (id INTEGER PRIMARY KEY, ticker TEXT NOT NULL, "
                "checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, payload TEXT NOT NULL)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_sec_monitor_ticker_id ON sec_monitor_checks(ticker, id DESC)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS position_plans (id INTEGER PRIMARY KEY, ticker TEXT NOT NULL, "
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, payload TEXT NOT NULL)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_position_plans_ticker_id ON position_plans(ticker, id DESC)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS decision_snapshots (id INTEGER PRIMARY KEY, report_id INTEGER UNIQUE, "
                "ticker TEXT NOT NULL, captured_at TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_decision_snapshots_ticker_id ON decision_snapshots(ticker, id DESC)")
            db.execute("CREATE TABLE IF NOT EXISTS discovery_runs (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, payload TEXT NOT NULL)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS discovery_scheduler_runs (id INTEGER PRIMARY KEY, "
                "started_at TEXT NOT NULL, completed_at TEXT, status TEXT NOT NULL, trigger TEXT NOT NULL, "
                "candidates INTEGER NOT NULL DEFAULT 0, alerts_created INTEGER NOT NULL DEFAULT 0, "
                "errors TEXT NOT NULL DEFAULT '[]')"
            )

    def watchlist(self) -> list[str]:
        with self._connect() as db:
            return [row["ticker"] for row in db.execute("SELECT ticker FROM watchlist ORDER BY ticker")]

    def add_ticker(self, ticker: str) -> None:
        ticker = _normalize_ticker(ticker)
        with self._connect() as db:
            db.execute("INSERT OR IGNORE INTO watchlist(ticker) VALUES (?)", (ticker,))

    def add_tickers(self, tickers: list[str]) -> int:
        normalized = list(dict.fromkeys(_normalize_ticker(ticker) for ticker in tickers))
        with self._connect() as db:
            before = db.total_changes
            db.executemany(
                "INSERT OR IGNORE INTO watchlist(ticker) VALUES (?)",
                ((ticker,) for ticker in normalized),
            )
            return db.total_changes - before

    def remove_ticker(self, ticker: str) -> None:
        ticker = _normalize_ticker(ticker)
        with self._connect() as db:
            db.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker,))

    def portfolio_holdings(self) -> list[str]:
        """Return companies held, without requiring allocation maintenance."""
        with self._connect() as db:
            return [row["ticker"] for row in db.execute(
                "SELECT ticker FROM portfolio_holdings ORDER BY ticker"
            )]

    def save_portfolio_holdings(self, tickers: list[str]) -> None:
        normalized = list(dict.fromkeys(_normalize_ticker(str(ticker)) for ticker in tickers))
        with self._connect() as db:
            db.execute("DELETE FROM portfolio_holdings")
            db.executemany(
                "INSERT INTO portfolio_holdings(ticker) VALUES (?)",
                ((ticker,) for ticker in normalized),
            )
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

    def save_thesis(self, thesis: dict[str, Any]) -> int:
        symbol = _normalize_ticker(str(thesis.get("ticker", "")))
        payload = {**thesis, "ticker": symbol}
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO theses(ticker, payload) VALUES (?, ?)", (symbol, json.dumps(payload))
            )
            return int(cursor.lastrowid)

    def thesis_history(self, ticker: str, limit: int = 20) -> list[dict[str, Any]]:
        symbol = _normalize_ticker(ticker)
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, ticker, created_at, payload FROM theses WHERE ticker = ? ORDER BY id DESC LIMIT ?",
                (symbol, max(1, limit)),
            ).fetchall()
        return [{**json.loads(row["payload"]), "id": row["id"], "created_at": row["created_at"]} for row in rows]

    def latest_theses(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT t.id, t.ticker, t.created_at, t.payload FROM theses t "
                "JOIN (SELECT ticker, MAX(id) AS latest_id FROM theses GROUP BY ticker) latest "
                "ON t.id = latest.latest_id ORDER BY t.ticker"
            ).fetchall()
        return [{**json.loads(row["payload"]), "id": row["id"], "created_at": row["created_at"]} for row in rows]

    def save_valuation(self, valuation: dict[str, Any]) -> int:
        symbol = _normalize_ticker(str(valuation.get("ticker", "")))
        payload = {**valuation, "ticker": symbol}
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO valuations(ticker, payload) VALUES (?, ?)", (symbol, json.dumps(payload))
            )
            return int(cursor.lastrowid)

    def valuation_history(self, ticker: str, limit: int = 20) -> list[dict[str, Any]]:
        symbol = _normalize_ticker(ticker)
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, ticker, created_at, payload FROM valuations WHERE ticker = ? ORDER BY id DESC LIMIT ?",
                (symbol, max(1, limit)),
            ).fetchall()
        return [{**json.loads(row["payload"]), "id": row["id"], "saved_at": row["created_at"]} for row in rows]

    def latest_valuations(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT v.id, v.ticker, v.created_at, v.payload FROM valuations v "
                "JOIN (SELECT ticker, MAX(id) AS latest_id FROM valuations GROUP BY ticker) latest "
                "ON v.id = latest.latest_id ORDER BY v.ticker"
            ).fetchall()
        return [{**json.loads(row["payload"]), "id": row["id"], "saved_at": row["created_at"]} for row in rows]

    def save_financial_health(self, result: dict[str, Any]) -> int:
        symbol = _normalize_ticker(str(result.get("ticker", "")))
        payload = {**result, "ticker": symbol}
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO financial_health(ticker, payload) VALUES (?, ?)",
                (symbol, json.dumps(payload)),
            )
            return int(cursor.lastrowid)

    def financial_health_history(self, ticker: str, limit: int = 20) -> list[dict[str, Any]]:
        symbol = _normalize_ticker(ticker)
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, ticker, created_at, payload FROM financial_health "
                "WHERE ticker = ? ORDER BY id DESC LIMIT ?",
                (symbol, max(1, limit)),
            ).fetchall()
        return [{**json.loads(row["payload"]), "id": row["id"], "saved_at": row["created_at"]} for row in rows]

    def latest_financial_health(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT f.id, f.ticker, f.created_at, f.payload FROM financial_health f "
                "JOIN (SELECT ticker, MAX(id) AS latest_id FROM financial_health GROUP BY ticker) latest "
                "ON f.id = latest.latest_id ORDER BY f.ticker"
            ).fetchall()
        return [{**json.loads(row["payload"]), "id": row["id"], "saved_at": row["created_at"]} for row in rows]

    def save_sec_monitor_check(self, result: dict[str, Any]) -> int:
        symbol = _normalize_ticker(str(result.get("Ticker", "")))
        payload = {**result, "Ticker": symbol}
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO sec_monitor_checks(ticker, payload) VALUES (?, ?)",
                (symbol, json.dumps(payload)),
            )
            return int(cursor.lastrowid)

    def latest_sec_monitor_checks(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT c.id, c.ticker, c.checked_at, c.payload FROM sec_monitor_checks c "
                "JOIN (SELECT ticker, MAX(id) AS latest_id FROM sec_monitor_checks GROUP BY ticker) latest "
                "ON c.id = latest.latest_id ORDER BY c.ticker"
            ).fetchall()
        return [
            {**json.loads(row["payload"]), "Check id": row["id"], "Saved check": row["checked_at"]}
            for row in rows
        ]

    def save_position_plan(self, plan: dict[str, Any]) -> int:
        symbol = _normalize_ticker(str(plan.get("ticker", "")))
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO position_plans(ticker, payload) VALUES (?, ?)",
                (symbol, json.dumps({**plan, "ticker": symbol})),
            )
            return int(cursor.lastrowid)

    def position_plan_history(self, ticker: str, limit: int = 20) -> list[dict[str, Any]]:
        symbol = _normalize_ticker(ticker)
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, created_at, payload FROM position_plans WHERE ticker = ? ORDER BY id DESC LIMIT ?",
                (symbol, max(1, limit)),
            ).fetchall()
        return [{**json.loads(row["payload"]), "id": row["id"], "saved_at": row["created_at"]} for row in rows]

    def save_decision_snapshot(self, snapshot: dict[str, Any]) -> int | None:
        symbol = _normalize_ticker(str(snapshot.get("ticker", "")))
        report_id = snapshot.get("report_id")
        with self._connect() as db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO decision_snapshots(report_id, ticker, captured_at, payload) VALUES (?, ?, ?, ?)",
                (report_id, symbol, snapshot["captured_at"], json.dumps({**snapshot, "ticker": symbol})),
            )
            return int(cursor.lastrowid) if cursor.rowcount else None

    def update_decision_snapshot(self, snapshot_id: int, snapshot: dict[str, Any]) -> None:
        with self._connect() as db:
            db.execute("UPDATE decision_snapshots SET payload = ? WHERE id = ?", (json.dumps(snapshot), int(snapshot_id)))

    def decision_snapshots(self, limit: int = 1000) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, payload FROM decision_snapshots ORDER BY id DESC LIMIT ?", (max(1, limit),)
            ).fetchall()
        return [{**json.loads(row["payload"]), "id": row["id"]} for row in rows]

    def save_discovery_run(self, result: dict[str, Any]) -> int:
        with self._connect() as db:
            cursor = db.execute("INSERT INTO discovery_runs(payload) VALUES (?)", (json.dumps(result),))
            return int(cursor.lastrowid)

    def latest_discovery_run(self) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT id, payload FROM discovery_runs ORDER BY id DESC LIMIT 1").fetchone()
        return {**json.loads(row["payload"]), "id": row["id"]} if row else None

    def discovery_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, created_at, payload FROM discovery_runs ORDER BY id DESC LIMIT ?", (max(1, limit),)
            ).fetchall()
        return [{**json.loads(row["payload"]), "id": row["id"], "saved_at": row["created_at"]} for row in rows]

    def start_discovery_scheduler_run(self, started_at: str, trigger: str) -> int:
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO discovery_scheduler_runs(started_at, status, trigger) VALUES (?, 'Running', ?)",
                (started_at, trigger),
            )
            return int(cursor.lastrowid)

    def finish_discovery_scheduler_run(
        self, run_id: int, completed_at: str, status: str, candidates: int,
        alerts_created: int, errors: list[str],
    ) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE discovery_scheduler_runs SET completed_at = ?, status = ?, candidates = ?, "
                "alerts_created = ?, errors = ? WHERE id = ?",
                (completed_at, status, int(candidates), int(alerts_created), json.dumps(errors), int(run_id)),
            )

    def discovery_scheduler_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM discovery_scheduler_runs ORDER BY id DESC LIMIT ?", (max(1, limit),)
            ).fetchall()
        return [{**dict(row), "errors": json.loads(row["errors"])} for row in rows]

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
        where = "WHERE expired = 0 AND is_read = 0" if unread_only else "WHERE expired = 0"
        with self._connect() as db:
            rows = db.execute(
                f"SELECT id, ticker, alert_type, severity, title, message, created_at, is_read, payload "
                f"FROM alerts {where} ORDER BY id DESC LIMIT ?", (max(1, limit),)
            ).fetchall()
        return [{**dict(row), "is_read": bool(row["is_read"]), "payload": json.loads(row["payload"])} for row in rows]

    def unread_alert_count(self) -> int:
        with self._connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM alerts WHERE is_read = 0 AND expired = 0").fetchone()[0])

    def expire_invalid_catalyst_alerts(self, today: date | None = None) -> int:
        """Archive expired and non-live catalyst alerts while retaining their audit records."""
        today = today or date.today()
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, payload FROM alerts WHERE alert_type = 'catalyst' AND expired = 0"
            ).fetchall()
            expired_ids = []
            for row in rows:
                try:
                    payload = json.loads(row["payload"])
                    event_date = date.fromisoformat(str(payload.get("date", "")))
                    valid_live_source = payload.get("source_live") is True
                except (TypeError, ValueError, json.JSONDecodeError):
                    event_date = None
                    valid_live_source = False
                if not valid_live_source or event_date is None or event_date < today:
                    expired_ids.append((int(row["id"]),))
            db.executemany("UPDATE alerts SET expired = 1, is_read = 1 WHERE id = ?", expired_ids)
        return len(expired_ids)

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
