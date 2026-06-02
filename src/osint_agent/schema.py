from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class CommandPayload:
    command: str
    subject: str | None = None
    subjects: List[str] | None = None
    pdf_sources: List[str] | None = None
    web_limit: int = 10
    archive_limit: int = 10
    follow_links: bool = True
    track_trails: bool = True
    crawl_depth: int = 1
    max_pages: int = 30
    link_limit: int = 20
    allow_domains: List[str] | None = None
    deny_domains: List[str] | None = None
    open_crawl: bool = False
    memory_db: str | None = None
    worker_urls: List[str] | None = None
    coordinator_url: str | None = None
    num_agents: int = 1
    mode: str = "parallel"
    top_k: int = 20
    token: str | None = None
    json_output: str | None = None
    csv_output: str | None = None


def _normalize_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def normalize_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    # Lightweight canonicalizer for incoming command payloads.
    if not isinstance(raw, dict):
        raise TypeError("payload must be a JSON object/dict")

    out: Dict[str, Any] = {}
    cmd = str(raw.get("command", "")).strip().lower()
    out["command"] = cmd

    subject = str(raw.get("subject", "")).strip()
    if subject:
        out["subject"] = subject
    subjects = _normalize_list(raw.get("subjects") or raw.get("subject") or [])
    if subjects:
        out["subjects"] = subjects

    out["pdf_sources"] = _normalize_list(raw.get("pdf_sources") or raw.get("pdf"))
    out["web_limit"] = int(raw.get("web_limit", 10))
    out["archive_limit"] = int(raw.get("archive_limit", 10))
    out["follow_links"] = bool(raw.get("follow_links", True))
    out["track_trails"] = bool(raw.get("track_trails", raw.get("track_target", True)))
    out["crawl_depth"] = int(raw.get("crawl_depth", 1))
    out["max_pages"] = int(raw.get("max_pages", 30))
    out["link_limit"] = int(raw.get("link_limit", 20))
    out["allow_domains"] = _normalize_list(raw.get("allow_domains") or raw.get("allow_domain"))
    out["deny_domains"] = _normalize_list(raw.get("deny_domains") or raw.get("deny_domain"))
    out["open_crawl"] = bool(raw.get("open_crawl", False))
    out["memory_db"] = raw.get("memory_db")
    out["worker_urls"] = _normalize_list(raw.get("worker_urls") or raw.get("worker_url"))
    out["coordinator_url"] = raw.get("coordinator_url")
    out["num_agents"] = int(raw.get("num_agents", raw.get("agents", 1)))
    out["mode"] = str(raw.get("mode", "parallel")).strip().lower()
    out["top_k"] = int(raw.get("top_k", 20))
    out["token"] = raw.get("token")
    out["json_output"] = raw.get("json_output")
    out["csv_output"] = raw.get("csv_output")

    return out


__all__ = ["CommandPayload", "normalize_payload"]
