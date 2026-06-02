from __future__ import annotations

from osint_agent.archive import search_wayback_snapshots


def test_search_wayback_snapshots(monkeypatch):
    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_get(url, params, timeout):
        assert "cdx" in url
        assert params["url"] == "https://example.com/deleted"
        return FakeResponse(
            [
                ["timestamp", "original", "statuscode", "mimetype"],
                ["20200102030405", "https://example.com/deleted", "200", "text/html"],
            ]
        )

    monkeypatch.setattr("osint_agent.archive.requests.get", fake_get)

    results = search_wayback_snapshots(["https://example.com/deleted"], per_url=1, memory=None)

    assert len(results) == 1
    first = results[0]
    assert first.source == "wayback_machine"
    assert first.url.startswith("https://web.archive.org/web/20200102030405/")
    assert "Wayback snapshot" in first.title
