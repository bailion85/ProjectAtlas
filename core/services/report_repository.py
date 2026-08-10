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

    def save(self, report: ResearchReport) -> int:
        with self._connect() as db:
            cursor = db.execute("INSERT INTO reports(ticker, created_at, payload) VALUES (?, ?, ?)", (report.ticker, report.created_at, json.dumps(report.to_dict())))
            return int(cursor.lastrowid)

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT id, ticker, created_at FROM reports ORDER BY id DESC LIMIT ?", (limit,))]

    def get(self, report_id: int) -> ResearchReport | None:
        with self._connect() as db:
            row = db.execute("SELECT payload FROM reports WHERE id = ?", (report_id,)).fetchone()
        if not row:
            return None
        data = json.loads(row["payload"])
        data["assessments"] = [AgentAssessment(**{**a, "evidence": [Evidence(**e) for e in a["evidence"]]}) for a in data["assessments"]]
        data["report_id"] = report_id
        return ResearchReport(**data)


def _normalize_ticker(ticker: str) -> str:
    normalized = ticker.strip().upper()
    if not normalized:
        raise ValueError("Ticker cannot be empty.")
    if len(normalized) > 15 or not all(character.isalnum() or character in ".-" for character in normalized):
        raise ValueError("Ticker contains unsupported characters.")
    return normalized
