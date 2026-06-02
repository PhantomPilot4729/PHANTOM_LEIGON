from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import sqlite3
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class CachedQuery:
    payload: list[dict[str, Any]]
    cached_at: str


@dataclass(slots=True)
class CachedPage:
    url: str
    final_url: str
    title: str
    html: str
    text: str
    content_type: str
    fetched_at: str


@dataclass(slots=True)
class CachedPdf:
    source: str
    page_count: int
    text: str
    content_hash: str
    cached_at: str


@dataclass(slots=True)
class FeedbackExample:
    subject: str
    source_url: str
    source_kind: str
    label: float
    features_json: str
    created_at: str


@dataclass(slots=True)
class ModelState:
    model_name: str
    payload_json: str
    updated_at: str


class OsintMemory:
    def __init__(self, db_path: str | Path = ".osint_memory.sqlite3") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "OsintMemory":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def get_query_cache(self, kind: str, cache_key: str) -> CachedQuery | None:
        row = self._conn.execute(
            "SELECT payload, cached_at FROM query_cache WHERE kind = ? AND cache_key = ?",
            (kind, cache_key),
        ).fetchone()
        if row is None:
            return None
        return CachedQuery(payload=json.loads(row["payload"]), cached_at=row["cached_at"])

    def set_query_cache(self, kind: str, cache_key: str, payload: list[dict[str, Any]]) -> None:
        self._conn.execute(
            """
            INSERT INTO query_cache(kind, cache_key, payload, cached_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(kind, cache_key) DO UPDATE SET
                payload = excluded.payload,
                cached_at = excluded.cached_at
            """,
            (kind, cache_key, json.dumps(payload), _utcnow()),
        )
        self._conn.commit()

    def get_page_cache(self, url: str) -> CachedPage | None:
        row = self._conn.execute(
            "SELECT url, final_url, title, html, text, content_type, fetched_at FROM page_cache WHERE url = ?",
            (url,),
        ).fetchone()
        if row is None:
            return None
        return CachedPage(
            url=row["url"],
            final_url=row["final_url"],
            title=row["title"],
            html=row["html"],
            text=row["text"],
            content_type=row["content_type"],
            fetched_at=row["fetched_at"],
        )

    def set_page_cache(self, url: str, final_url: str, title: str, html: str, text: str, content_type: str) -> None:
        self._conn.execute(
            """
            INSERT INTO page_cache(url, final_url, title, html, text, content_type, fetched_at)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                final_url = excluded.final_url,
                title = excluded.title,
                html = excluded.html,
                text = excluded.text,
                content_type = excluded.content_type,
                fetched_at = excluded.fetched_at
            """,
            (url, final_url, title, html, text, content_type, _utcnow()),
        )
        self._conn.commit()

    def get_link_cache(self, page_url: str) -> list[dict[str, Any]] | None:
        row = self._conn.execute(
            "SELECT links_json FROM link_cache WHERE page_url = ?",
            (page_url,),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["links_json"])

    def set_link_cache(self, page_url: str, links: list[dict[str, Any]]) -> None:
        self._conn.execute(
            """
            INSERT INTO link_cache(page_url, links_json, fetched_at)
            VALUES(?, ?, ?)
            ON CONFLICT(page_url) DO UPDATE SET
                links_json = excluded.links_json,
                fetched_at = excluded.fetched_at
            """,
            (page_url, json.dumps(links), _utcnow()),
        )
        self._conn.commit()

    def get_pdf_cache(self, source: str) -> CachedPdf | None:
        row = self._conn.execute(
            "SELECT source, page_count, text, content_hash, cached_at FROM pdf_cache WHERE source = ?",
            (source,),
        ).fetchone()
        if row is None:
            return None
        return CachedPdf(
            source=row["source"],
            page_count=int(row["page_count"]),
            text=row["text"],
            content_hash=row["content_hash"],
            cached_at=row["cached_at"],
        )

    def set_pdf_cache(self, source: str, page_count: int, text: str, content_hash: str) -> None:
        self._conn.execute(
            """
            INSERT INTO pdf_cache(source, page_count, text, content_hash, cached_at)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(source) DO UPDATE SET
                page_count = excluded.page_count,
                text = excluded.text,
                content_hash = excluded.content_hash,
                cached_at = excluded.cached_at
            """,
            (source, page_count, text, content_hash, _utcnow()),
        )
        self._conn.commit()

    def add_feedback(self, subject: str, source_url: str, source_kind: str, label: float, features_json: str) -> None:
        self._conn.execute(
            """
            INSERT INTO feedback_examples(subject, source_url, source_kind, label, features_json, created_at)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (subject, source_url, source_kind, float(label), features_json, _utcnow()),
        )
        self._conn.commit()

    def list_feedback_examples(self) -> list[FeedbackExample]:
        rows = self._conn.execute(
            "SELECT subject, source_url, source_kind, label, features_json, created_at FROM feedback_examples ORDER BY created_at ASC"
        ).fetchall()
        return [
            FeedbackExample(
                subject=row["subject"],
                source_url=row["source_url"],
                source_kind=row["source_kind"],
                label=float(row["label"]),
                features_json=row["features_json"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def get_model_state(self, model_name: str = "neural_ranker") -> ModelState | None:
        row = self._conn.execute(
            "SELECT model_name, payload_json, updated_at FROM model_state WHERE model_name = ?",
            (model_name,),
        ).fetchone()
        if row is None:
            return None
        return ModelState(model_name=row["model_name"], payload_json=row["payload_json"], updated_at=row["updated_at"])

    def set_model_state(self, model_name: str, payload_json: str) -> None:
        self._conn.execute(
            """
            INSERT INTO model_state(model_name, payload_json, updated_at)
            VALUES(?, ?, ?)
            ON CONFLICT(model_name) DO UPDATE SET
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (model_name, payload_json, _utcnow()),
        )
        self._conn.commit()

    def mark_visit(self, url: str, parent_url: str, depth: int, kind: str, title: str, notes: str = "") -> None:
        self._conn.execute(
            """
            INSERT INTO crawl_visit(url, parent_url, depth, kind, title, notes, last_seen)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                parent_url = excluded.parent_url,
                depth = excluded.depth,
                kind = excluded.kind,
                title = excluded.title,
                notes = excluded.notes,
                last_seen = excluded.last_seen
            """,
            (url, parent_url, depth, kind, title, notes, _utcnow()),
        )
        self._conn.commit()

    def has_visited(self, url: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM crawl_visit WHERE url = ?", (url,)).fetchone()
        return row is not None

    def stats(self) -> dict[str, int]:
        return {
            "queries": self._count("query_cache"),
            "pages": self._count("page_cache"),
            "links": self._count("link_cache"),
            "pdfs": self._count("pdf_cache"),
            "visits": self._count("crawl_visit"),
        }

    def _count(self, table: str) -> int:
        row = self._conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
        return int(row["count"] if row is not None else 0)

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS query_cache(
                kind TEXT NOT NULL,
                cache_key TEXT NOT NULL,
                payload TEXT NOT NULL,
                cached_at TEXT NOT NULL,
                PRIMARY KEY(kind, cache_key)
            );

            CREATE TABLE IF NOT EXISTS page_cache(
                url TEXT PRIMARY KEY,
                final_url TEXT NOT NULL,
                title TEXT NOT NULL,
                html TEXT NOT NULL,
                text TEXT NOT NULL,
                content_type TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS link_cache(
                page_url TEXT PRIMARY KEY,
                links_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pdf_cache(
                source TEXT PRIMARY KEY,
                page_count INTEGER NOT NULL,
                text TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                cached_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS crawl_visit(
                url TEXT PRIMARY KEY,
                parent_url TEXT NOT NULL,
                depth INTEGER NOT NULL,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                notes TEXT NOT NULL,
                last_seen TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS feedback_examples(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                source_url TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                label REAL NOT NULL,
                features_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS model_state(
                model_name TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        self._conn.commit()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()