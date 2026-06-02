from __future__ import annotations

from collections import defaultdict

from .crawler import CrawlResult


def build_crawl_tree(crawl_result: CrawlResult) -> str:
    children: dict[str, list[str]] = defaultdict(list)
    labels: dict[str, str] = {}

    for link in crawl_result.discovered_links:
        children[link.source_page].append(link.url)
        labels[link.url] = _label_for(link.url, link.text, link.is_pdf, getattr(link, "trail_score", 0.0), getattr(link, "trail_strayed", False))
        labels.setdefault(link.source_page, _label_for(link.source_page, "", False))

    roots = [url for url in crawl_result.visited_urls if url not in {link.url for link in crawl_result.discovered_links}]
    roots = roots or list(crawl_result.visited_urls[:1])

    lines: list[str] = ["## Crawl Tree"]
    if not roots:
        lines.append("- No crawl tree available.")
        return "\n".join(lines)

    seen: set[str] = set()
    for root in roots:
        _append_tree(lines, root, children, labels, seen, prefix="")
    return "\n".join(lines)


def _append_tree(
    lines: list[str],
    url: str,
    children: dict[str, list[str]],
    labels: dict[str, str],
    seen: set[str],
    prefix: str,
) -> None:
    if url in seen:
        lines.append(f"{prefix}- {labels.get(url, url)} (seen)")
        return
    seen.add(url)
    lines.append(f"{prefix}- {labels.get(url, url)}")
    child_urls = children.get(url, [])
    for index, child in enumerate(child_urls):
        is_last = index == len(child_urls) - 1
        branch = "└─ " if is_last else "├─ "
        next_prefix = prefix + ("   " if is_last else "│  ")
        if child in seen:
            lines.append(f"{prefix}{branch}{labels.get(child, child)} (seen)")
            continue
        _append_tree(lines, child, children, labels, seen, next_prefix)


def _label_for(url: str, text: str, is_pdf: bool, trail_score: float = 0.0, trail_strayed: bool = False) -> str:
    suffix = " [PDF]" if is_pdf else ""
    trail_note = f" [trail={trail_score:.1f}{' stray' if trail_strayed else ''}]" if trail_score else ""
    if text:
        return f"{text} -> {url}{suffix}{trail_note}"
    return f"{url}{suffix}{trail_note}"