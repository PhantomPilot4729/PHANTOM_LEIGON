from __future__ import annotations

from osint_agent.crawler import crawl_sources
from osint_agent.links import LinkResult


def test_track_trails_follows_pointer_chain(monkeypatch):
    graph = {
        "https://example.com/seed": [
            LinkResult(
                source_page="https://example.com/seed",
                url="https://example.com/profile-pointer",
                text="Read profile of Jane Doe here",
                is_pdf=False,
            )
        ],
        "https://example.com/profile-pointer": [
            LinkResult(
                source_page="https://example.com/profile-pointer",
                url="https://example.com/final-dossier",
                text="official dossier archive",
                is_pdf=False,
            )
        ],
        "https://example.com/final-dossier": [],
    }

    def fake_discover_links(page_url, max_links=20, memory=None):
        return list(graph.get(page_url, []))

    monkeypatch.setattr("osint_agent.crawler.discover_links", fake_discover_links)

    result = crawl_sources(
        ["https://example.com/seed"],
        subject="Jane Doe",
        track_trails=True,
        max_depth=0,
        trail_depth_bonus=3,
        max_pages=10,
        allow_domains=["example.com"],
    )

    assert "https://example.com/final-dossier" in result.visited_urls


def test_no_trail_tracking_stops_at_depth(monkeypatch):
    graph = {
        "https://example.com/seed": [
            LinkResult(
                source_page="https://example.com/seed",
                url="https://example.com/profile-pointer",
                text="Read profile of Jane Doe here",
                is_pdf=False,
            )
        ],
        "https://example.com/profile-pointer": [
            LinkResult(
                source_page="https://example.com/profile-pointer",
                url="https://example.com/final-dossier",
                text="official dossier archive",
                is_pdf=False,
            )
        ],
        "https://example.com/final-dossier": [],
    }

    def fake_discover_links(page_url, max_links=20, memory=None):
        return list(graph.get(page_url, []))

    monkeypatch.setattr("osint_agent.crawler.discover_links", fake_discover_links)

    result = crawl_sources(
        ["https://example.com/seed"],
        subject="Jane Doe",
        track_trails=False,
        max_depth=0,
        trail_depth_bonus=3,
        max_pages=10,
        allow_domains=["example.com"],
    )

    assert "https://example.com/final-dossier" not in result.visited_urls
