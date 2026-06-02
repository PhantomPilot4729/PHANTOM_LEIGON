from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import requests

from .memory import OsintMemory

ARCHIVE_SEARCH_URL = "https://archive.org/advancedsearch.php"
ARCHIVE_DETAILS_URL = "https://archive.org/details/{identifier}"
WAYBACK_CDX_URL = "https://web.archive.org/cdx/search/cdx"
WAYBACK_SNAPSHOT_URL = "https://web.archive.org/web/{timestamp}/{original}"


@dataclass(slots=True)
class ArchiveResult:
    identifier: str
    title: str
    description: str
    date: str
    mediatype: str
    url: str
    source: str = "internet_archive"


def search_archive(query: str, max_results: int = 10, memory: OsintMemory | None = None) -> list[ArchiveResult]:
    cache_key = f"{query}|{max_results}"
    if memory is not None:
        cached = memory.get_query_cache("archive", cache_key)
        if cached is not None:
            return [ArchiveResult(**item) for item in cached.payload]

    params = {
        "q": query,
        "fl[]": ["identifier", "title", "description", "date", "mediatype"],
        "rows": max_results,
        "page": 1,
        "output": "json",
    }
    response = requests.get(ARCHIVE_SEARCH_URL, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    docs = payload.get("response", {}).get("docs", [])

    results: list[ArchiveResult] = []
    for doc in docs:
        identifier = str(doc.get("identifier") or "").strip()
        if not identifier:
            continue
        results.append(
            ArchiveResult(
                identifier=identifier,
                title=str(doc.get("title") or "").strip(),
                description=str(doc.get("description") or "").strip(),
                date=str(doc.get("date") or "").strip(),
                mediatype=str(doc.get("mediatype") or "").strip(),
                url=ARCHIVE_DETAILS_URL.format(identifier=identifier),
            )
        )

    if memory is not None:
        memory.set_query_cache("archive", cache_key, [result_to_dict(result) for result in results])

    return results


def search_wayback_snapshots(
    urls: list[str],
    *,
    per_url: int = 2,
    memory: OsintMemory | None = None,
) -> list[ArchiveResult]:
    cleaned_urls = [url.strip() for url in urls if url and url.strip()]
    if not cleaned_urls:
        return []

    cache_key = f"{','.join(sorted(set(cleaned_urls)))}|{per_url}"
    if memory is not None:
        cached = memory.get_query_cache("wayback", cache_key)
        if cached is not None:
            return [ArchiveResult(**item) for item in cached.payload]

    results: list[ArchiveResult] = []
    seen_snapshot_urls: set[str] = set()
    for original_url in cleaned_urls:
        try:
            snapshots = _wayback_for_url(original_url, limit=per_url)
        except requests.RequestException:
            continue
        for snapshot in snapshots:
            if snapshot.url in seen_snapshot_urls:
                continue
            seen_snapshot_urls.add(snapshot.url)
            results.append(snapshot)

    if memory is not None:
        memory.set_query_cache("wayback", cache_key, [result_to_dict(result) for result in results])

    return results


def _wayback_for_url(original_url: str, *, limit: int) -> list[ArchiveResult]:
    params = {
        "url": original_url,
        "output": "json",
        "fl": "timestamp,original,statuscode,mimetype",
        "filter": "statuscode:200",
        "collapse": "digest",
        "limit": max(1, int(limit)),
        "from": "1990",
        "to": "2099",
    }
    response = requests.get(WAYBACK_CDX_URL, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    # CDX JSON returns a header row followed by rows.
    rows = payload[1:] if payload and isinstance(payload, list) else []
    results: list[ArchiveResult] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 4:
            continue
        timestamp = str(row[0]).strip()
        original = str(row[1]).strip()
        mimetype = str(row[3]).strip()
        if not timestamp or not original:
            continue
        snapshot_url = WAYBACK_SNAPSHOT_URL.format(timestamp=timestamp, original=quote(original, safe=':/?#[]@!$&\'()*+,;=%'))
        date = _timestamp_to_iso(timestamp)
        results.append(
            ArchiveResult(
                identifier=f"wayback:{timestamp}:{original}",
                title=f"Wayback snapshot: {original}",
                description=f"Archived snapshot for {original} at {date}",
                date=date,
                mediatype=mimetype or "wayback_snapshot",
                url=snapshot_url,
                source="wayback_machine",
            )
        )
    return results


def _timestamp_to_iso(timestamp: str) -> str:
    try:
        dt = datetime.strptime(timestamp[:14], "%Y%m%d%H%M%S")
        return dt.replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return timestamp


def result_to_dict(result: ArchiveResult) -> dict[str, Any]:
    return {
        "source": result.source,
        "identifier": result.identifier,
        "title": result.title,
        "description": result.description,
        "date": result.date,
        "mediatype": result.mediatype,
        "url": result.url,
    }
