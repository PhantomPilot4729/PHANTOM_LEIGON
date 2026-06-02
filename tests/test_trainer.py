import pytest
from pathlib import Path


torch = pytest.importorskip("torch")

from osint_agent.memory import OsintMemory
from osint_agent.learning import build_features, train_model


def test_trainer_creates_checkpoint(tmp_path: Path):
    db = tmp_path / "memory.sqlite3"
    with OsintMemory(db) as memory:
        # add minimal feedback
        for i in range(6):
            url = f"https://example.com/p{i}"
            feats = build_features("test-subject", kind="web", title=f"T{i}", url=url, text="txt", source_score=50.0)
            memory.add_feedback("test-subject", url, "web", float(i % 2), __import__("json").dumps({"features": feats}))
        stats, metrics, ck = train_model(memory, epochs=2, lr=0.01, pairs_strategy="random", pairs_per_subject=10, val_split=0.2, device="cpu")
    assert stats.examples >= 1
    assert Path(ck).exists()


def test_build_features_includes_trail_signals():
    baseline = build_features("alpha beta", kind="web", title="alpha", url="https://example.com", text="alpha", source_score=50.0)
    trail = build_features(
        "alpha beta",
        kind="web",
        title="alpha",
        url="https://example.com",
        text="alpha",
        source_score=50.0,
        trail_depth=4,
        trail_score=12.0,
        trail_strayed=True,
    )

    assert len(trail) == len(baseline)
    assert trail[-5] > 0.0
    assert trail[-4] > 0.0
    assert trail[-3] == 1.0
    assert trail[-5] != baseline[-5]
    assert trail[-4] != baseline[-4]
    assert trail[-3] != baseline[-3]
