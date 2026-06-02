from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Iterable


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_csv(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    fieldnames = _fieldnames(rows)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _stringify(row.get(field, "")) for field in fieldnames})


def write_maltego_csv(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    fieldnames = [
        "Entity Type",
        "Value",
        "Notes",
        "Subject",
        "Score",
        "Frequency",
        "Kinds",
        "Titles",
        "Sources",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _stringify(row.get(field, "")) for field in fieldnames})


def legion_results_to_maltego_rows(results: Iterable[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for result in results:
        subject = str(getattr(result, "subject", "")).strip()
        merged_sources = getattr(result, "merged_sources", None) or []
        if merged_sources:
            for item in merged_sources:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url", "")).strip()
                if not url:
                    continue
                key = (subject, url)
                if key in seen:
                    continue
                seen.add(key)
                titles = item.get("titles", []) or []
                if isinstance(titles, str):
                    titles = [titles]
                reasons = item.get("reasons", []) or []
                if isinstance(reasons, str):
                    reasons = [reasons]
                kinds = item.get("kinds", []) or []
                if isinstance(kinds, str):
                    kinds = [kinds]
                rows.append(
                    {
                        "Entity Type": "Website",
                        "Value": url,
                        "Notes": _compact_note(subject, titles, reasons, kinds),
                        "Subject": subject,
                        "Score": f"{float(item.get('weight', item.get('avg_score', 0.0))):.2f}",
                        "Frequency": str(item.get("freq", 0)),
                        "Kinds": ", ".join(sorted({str(kind) for kind in kinds if kind})),
                        "Titles": ", ".join(str(title) for title in titles if title),
                        "Sources": ", ".join(str(source) for source in item.get("sources", []) if source),
                    }
                )
            continue

        report_text = str(getattr(result, "merged_report", "") or getattr(result, "report", "") or "")
        for url in re.findall(r'https?://[^\s<>"]+', report_text):
            key = (subject, url)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "Entity Type": "Website",
                    "Value": url,
                    "Notes": subject,
                    "Subject": subject,
                    "Score": "",
                    "Frequency": "1",
                    "Kinds": "",
                    "Titles": "",
                    "Sources": "",
                }
            )
    return rows


def _fieldnames(rows: list[dict[str, Any]]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            if key in seen:
                continue
            seen.add(key)
            keys.append(key)
    return keys or ["value"]


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _compact_note(subject: str, titles: list[Any], reasons: list[Any], kinds: list[Any]) -> str:
    parts = [part for part in [subject, "; ".join(str(title) for title in titles if title), "; ".join(str(reason) for reason in reasons if reason), ", ".join(str(kind) for kind in kinds if kind)] if part]
    return " | ".join(parts)