from pathlib import Path
import json
from osint_agent.memory import OsintMemory
from osint_agent.learning import build_features, train_model


def make_dummy_feedback(memory: OsintMemory, subject: str, base_url: str, n: int = 6) -> None:
    for i in range(n):
        url = f"{base_url}/page{i}.html"
        feats = build_features(subject, kind="web", title=f"Title {i}", url=url, text=f"Sample text {i}", source_score=50.0)
        payload = json.dumps({"features": feats})
        memory.add_feedback(subject, url, "web", float(i % 2), payload)


def main() -> None:
    db = Path(".smoke_memory.sqlite3")
    if db.exists():
        db.unlink()
    with OsintMemory(db) as memory:
        make_dummy_feedback(memory, "smoke-subject", "https://example.com", n=8)
        stats, metrics, ck = train_model(memory, epochs=2, lr=0.01, pairs_strategy="random", pairs_per_subject=20, val_split=0.2, device="cpu")
        print(f"Training done: examples={stats.examples}, loss={stats.loss:.4f}, ndcg@10={metrics.ndcg_at_10:.4f}, mrr={metrics.mrr:.4f}")
        print("checkpoint:", ck)


if __name__ == "__main__":
    main()
