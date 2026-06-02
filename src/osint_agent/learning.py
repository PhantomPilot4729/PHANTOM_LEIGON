from __future__ import annotations

from dataclasses import dataclass
import json
import os

import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np

from .memory import OsintMemory


@dataclass(slots=True)
class TrainingStats:
    examples: int
    epochs: int
    loss: float


@dataclass(slots=True)
class EvaluationMetrics:
    ndcg_at_10: float
    mrr: float


class TorchRanker(nn.Module):
    def __init__(self, input_size: int, hidden_size: int = 64) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_size, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, hidden_size // 2),
            nn.ReLU(),
            nn.Linear(hidden_size // 2, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x).squeeze(-1)


def build_features(
    subject: str,
    *,
    kind: str,
    title: str,
    url: str,
    text: str,
    source_score: float,
    trail_depth: int = 0,
    trail_score: float = 0.0,
    trail_strayed: bool = False,
) -> list[float]:
    # Recreate the same features as before but return list for serialization
    subject_tokens = [t for t in ("".join(ch for ch in raw if ch.isalnum()) for raw in subject.lower().split()) if len(t) >= 3]
    haystacks = [title.lower(), url.lower(), text.lower()]
    matches = sum(1 for token in subject_tokens if any(token in hay for hay in haystacks))
    url_lower = url.lower()
    title_lower = title.lower()
    text_lower = text.lower()
    domain = _host(url)

    def _norm(v, lo, hi):
        if hi <= lo:
            return 0.0
        return float(max(0.0, min(1.0, (v - lo) / (hi - lo))))

    features = [
        1.0,
        _norm(source_score, 0.0, 100.0),
        _norm(len(subject_tokens), 0.0, 12.0),
        _norm(matches, 0.0, 12.0),
        _norm(len(title), 0.0, 160.0),
        _norm(len(url), 0.0, 220.0),
        _norm(len(text), 0.0, 4000.0),
        1.0 if kind == "web" else 0.0,
        1.0 if kind == "archive" else 0.0,
        1.0 if kind in {"pdf", "linked_pdf"} else 0.0,
        1.0 if url_lower.endswith(".pdf") else 0.0,
        1.0 if domain.endswith((".gov", ".edu", ".mil")) else 0.0,
        1.0 if "archive.org" in url_lower else 0.0,
        1.0 if any(term in title_lower or term in text_lower for term in ("report", "study", "analysis", "paper")) else 0.0,
        _norm(float(trail_depth), 0.0, 8.0),
        _norm(float(trail_score), 0.0, 20.0),
        1.0 if trail_strayed else 0.0,
        _norm(float(trail_depth if trail_strayed else 0.0), 0.0, 8.0),
        _norm(float(trail_score if trail_strayed else 0.0), 0.0, 20.0),
    ]
    return features


def _host(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).hostname or ""


def label_to_target(label: float) -> float:
    # normalize label to 0..1
    if label <= 1.0:
        return float(max(0.0, min(1.0, label)))
    return float(max(0.0, min(1.0, label / 100.0)))


def train_model(
    memory: OsintMemory,
    *,
    epochs: int = 50,
    lr: float = 1e-3,
    margin: float = 0.1,
    checkpoint_path: str | None = None,
    device: str = "cpu",
    pairs_strategy: str = "all",  # 'all' or 'random'
    pairs_per_subject: int | None = None,
    val_split: float = 0.2,
    early_stopping_patience: int = 5,
    early_stopping_min_delta: float = 1e-4,
    lr_scheduler: str | None = None,  # None, 'plateau' or 'step'
    step_lr_step: int = 10,
    step_lr_gamma: float = 0.5,
    seed: int = 42,
) -> tuple[TrainingStats, EvaluationMetrics, str]:
    # Load feedback grouped by subject
    examples = memory.list_feedback_examples()
    if not examples:
        return TrainingStats(0, 0, 0.0), EvaluationMetrics(0.0, 0.0), ""

    by_subject: dict[str, list[tuple[list[float], float]]] = {}
    for ex in examples:
        payload = json.loads(ex.features_json)
        feats = payload.get("features")
        if feats is None:
            continue
        by_subject.setdefault(ex.subject, []).append((feats, label_to_target(ex.label)))

    # Determine feature size
    input_size = max(len(feats) for items in by_subject.values() for feats, _ in items)

    def _pad_feature_vector(values: list[float]) -> list[float]:
        if len(values) >= input_size:
            return list(values[:input_size])
        return list(values) + [0.0] * (input_size - len(values))

    for subject, items in list(by_subject.items()):
        by_subject[subject] = [(_pad_feature_vector(list(feats)), target) for feats, target in items]

    model = TorchRanker(input_size=input_size, hidden_size=max(16, input_size * 2)).to(device)
    opt = optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.MarginRankingLoss(margin=margin)

    # Split subjects into train / val
    import random

    subjects = list(by_subject.keys())
    random.Random(seed).shuffle(subjects)
    n_val = max(0, int(len(subjects) * val_split)) if val_split and 0.0 < val_split < 1.0 else 0
    val_subjects = set(subjects[:n_val])
    train_subjects = [s for s in subjects if s not in val_subjects]

    # Build pairs for train and val subjects
    pairs_train: list[tuple[np.ndarray, np.ndarray, float]] = []
    pairs_val: list[tuple[np.ndarray, np.ndarray, float]] = []
    for subject in train_subjects:
        items = by_subject[subject]
        n = len(items)
        valid_pairs: list[tuple[int, int]] = []
        for i in range(n):
            for j in range(n):
                if items[i][1] <= items[j][1]:
                    continue
                valid_pairs.append((i, j))
        if not valid_pairs:
            continue
        if pairs_strategy == "all" or pairs_per_subject is None:
            chosen = valid_pairs
        else:
            k = min(len(valid_pairs), int(pairs_per_subject))
            chosen = random.Random(seed).sample(valid_pairs, k)
        for (i, j) in chosen:
            pairs_train.append((np.array(items[i][0], dtype=float), np.array(items[j][0], dtype=float), 1.0))
    for subject in val_subjects:
        items = by_subject.get(subject, [])
        n = len(items)
        valid_pairs: list[tuple[int, int]] = []
        for i in range(n):
            for j in range(n):
                if items[i][1] <= items[j][1]:
                    continue
                valid_pairs.append((i, j))
        for (i, j) in valid_pairs:
            pairs_val.append((np.array(items[i][0], dtype=float), np.array(items[j][0], dtype=float), 1.0))

    if not pairs_train:
        return TrainingStats(0, 0, 0.0), EvaluationMetrics(0.0, 0.0), ""

    X_a = torch.tensor(np.vstack([p[0] for p in pairs_train]), dtype=torch.float32, device=device)
    X_b = torch.tensor(np.vstack([p[1] for p in pairs_train]), dtype=torch.float32, device=device)
    y = torch.tensor([p[2] for p in pairs_train], dtype=torch.float32, device=device)

    if pairs_val:
        X_val_a = torch.tensor(np.vstack([p[0] for p in pairs_val]), dtype=torch.float32, device=device)
        X_val_b = torch.tensor(np.vstack([p[1] for p in pairs_val]), dtype=torch.float32, device=device)
        y_val = torch.tensor([p[2] for p in pairs_val], dtype=torch.float32, device=device)
    else:
        X_val_a = X_val_b = y_val = None

    last_loss = 0.0
    batch_size = min(256, len(pairs_train))
    # Optional LR scheduler
    scheduler = None
    if lr_scheduler == "step":
        scheduler = optim.lr_scheduler.StepLR(opt, step_size=step_lr_step, gamma=step_lr_gamma)
    elif lr_scheduler == "plateau":
        scheduler = optim.lr_scheduler.ReduceLROnPlateau(opt, mode="min", factor=step_lr_gamma, patience=max(1, early_stopping_patience // 2))

    best_val_loss = float("inf")
    epochs_no_improve = 0
    train_pairs_len = len(pairs_train)
    history: list[dict] = []
    for epoch in range(epochs):
        perm = torch.randperm(train_pairs_len)
        epoch_loss = 0.0
        for i in range(0, train_pairs_len, batch_size):
            idx = perm[i : i + batch_size]
            a = X_a[idx]
            b = X_b[idx]
            target = y[idx]
            opt.zero_grad()
            sa = model(a)
            sb = model(b)
            loss = loss_fn(sa, sb, target)
            loss.backward()
            opt.step()
            epoch_loss += float(loss.item()) * len(idx)
        last_loss = epoch_loss / train_pairs_len

        # compute val loss if available
        val_loss = None
        if X_val_a is not None:
            with torch.no_grad():
                sva = model(X_val_a)
                svb = model(X_val_b)
                val_loss = float(loss_fn(sva, svb, y_val).item())

        # scheduler step
        if isinstance(scheduler, optim.lr_scheduler.ReduceLROnPlateau) and val_loss is not None:
            scheduler.step(val_loss)
        elif isinstance(scheduler, optim.lr_scheduler._LRScheduler):
            scheduler.step()

        # early stopping check
        if val_loss is not None:
            if val_loss + early_stopping_min_delta < best_val_loss:
                best_val_loss = val_loss
                epochs_no_improve = 0
            else:
                epochs_no_improve += 1
            if early_stopping_patience and epochs_no_improve >= early_stopping_patience:
                break
        # record history for this epoch
        current_lr = float(opt.param_groups[0]["lr"]) if opt.param_groups else lr
        history.append({"epoch": epoch + 1, "train_loss": last_loss, "val_loss": val_loss, "lr": current_lr})

    # Save checkpoint
    ck_dir = os.path.dirname(checkpoint_path) if checkpoint_path else "models"
    os.makedirs(ck_dir, exist_ok=True)
    checkpoint_path = checkpoint_path or os.path.join("models", "neural_ranker.pt")
    torch.save({"state_dict": model.state_dict(), "input_size": input_size}, checkpoint_path)

    # store model metadata in memory
    model_meta = {"input_size": input_size, "hidden_size": max(16, input_size * 2), "checkpoint": checkpoint_path, "history": history}
    memory.set_model_state("neural_ranker", json.dumps(model_meta))

    # Evaluate on validation subjects (if any), otherwise evaluate on all subjects
    eval_subjects = list(val_subjects) if val_subjects else list(by_subject.keys())
    ndcg_total = 0.0
    mrr_total = 0.0
    subjects_evaluated = 0
    model.eval()
    with torch.no_grad():
        for subject in eval_subjects:
            items = by_subject.get(subject, [])
            if not items:
                continue
            feats = torch.tensor(np.vstack([it[0] for it in items]), dtype=torch.float32, device=device)
            labels = [it[1] for it in items]
            scores = model(feats).cpu().numpy()
            order = np.argsort(-scores)
            ranked_labels = [labels[i] for i in order]
            # DCG
            dcg = 0.0
            for rank, rel in enumerate(ranked_labels, start=1):
                dcg += (2 ** rel - 1) / np.log2(rank + 1)
            ideal = sorted(labels, reverse=True)
            idcg = 0.0
            for rank, rel in enumerate(ideal, start=1):
                idcg += (2 ** rel - 1) / np.log2(rank + 1)
            ndcg = (dcg / idcg) if idcg > 0 else 0.0
            ndcg_total += ndcg
            # MRR (first relevant label > 0.5)
            rr = 0.0
            for idx, rel in enumerate(ranked_labels, start=1):
                if rel > 0.5:
                    rr = 1.0 / idx
                    break
            mrr_total += rr
            subjects_evaluated += 1

    ndcg_avg = ndcg_total / subjects_evaluated if subjects_evaluated else 0.0
    mrr_avg = mrr_total / subjects_evaluated if subjects_evaluated else 0.0

    return TrainingStats(examples=len(pairs_train), epochs=epochs, loss=last_loss), EvaluationMetrics(ndcg_avg, mrr_avg), checkpoint_path


def load_model_from_memory(memory: OsintMemory, device: str = "cpu") -> torch.nn.Module | None:
    state = memory.get_model_state()
    if not state:
        return None
    payload = json.loads(state.payload_json)
    checkpoint = payload.get("checkpoint")
    input_size = int(payload.get("input_size", 0))
    hidden_size = int(payload.get("hidden_size", max(16, input_size * 2)))
    if not checkpoint or not os.path.exists(checkpoint):
        return None
    model = TorchRanker(input_size=input_size, hidden_size=hidden_size).to(device)
    ck = torch.load(checkpoint, map_location=device)
    model.load_state_dict(ck["state_dict"])
    model.eval()
    return model


def rank_with_model(subject: str, items: list, memory: OsintMemory | None = None) -> list:
    if memory is None:
        return items
    model = load_model_from_memory(memory)
    if model is None:
        return items

    reranked = []
    for item in items:
        feats = np.array(
            build_features(
                subject,
                kind=item.kind,
                title=item.title,
                url=item.url,
                text=item.reason,
                source_score=float(item.score),
                trail_depth=int(getattr(item, "trail_depth", 0) or 0),
                trail_score=float(getattr(item, "trail_score", 0.0) or 0.0),
                trail_strayed=bool(getattr(item, "trail_strayed", False)),
            ),
            dtype=float,
        )
        feats = _align_features(feats, model)
        tensor = torch.tensor(feats, dtype=torch.float32).unsqueeze(0)
        with torch.no_grad():
            raw = float(model(tensor).item())
            learned = float(torch.sigmoid(torch.tensor(raw)).item())
        combined = int(round((0.7 * float(item.score)) + (0.3 * learned * 100.0)))
        from .ranking import RankedSource

        reranked.append(
            RankedSource(
                kind=item.kind,
                score=min(max(combined, 0), 100),
                title=item.title,
                url=item.url,
                reason=f"{item.reason}; learned={learned:.4f}",
                source=item.source,
                heuristic_score=getattr(item, "heuristic_score", 0),
                learned_score=learned,
                trail_depth=int(getattr(item, "trail_depth", 0) or 0),
                trail_score=float(getattr(item, "trail_score", 0.0) or 0.0),
                trail_strayed=bool(getattr(item, "trail_strayed", False)),
                path_confidence=float(getattr(item, "path_confidence", 0.0) or 0.0),
                drift_score=float(getattr(item, "drift_score", 0.0) or 0.0),
            )
        )
    return sorted(reranked, key=lambda it: it.score, reverse=True)


def _align_features(features: np.ndarray, model: torch.nn.Module) -> np.ndarray:
    input_size = _model_input_size(model)
    if input_size <= 0:
        return features
    if len(features) == input_size:
        return features
    if len(features) > input_size:
        return features[:input_size]
    padding = np.zeros(input_size - len(features), dtype=float)
    return np.concatenate([features, padding])


def _model_input_size(model: torch.nn.Module) -> int:
    for module in model.modules():
        if isinstance(module, nn.Linear):
            return int(module.in_features)
    return 0
