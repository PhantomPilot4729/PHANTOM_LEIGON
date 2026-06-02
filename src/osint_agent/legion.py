from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json
from typing import Iterable, List, Optional
import subprocess
import re
import time
from urllib import request as urllib_request
from urllib.error import URLError, HTTPError
from urllib.parse import urljoin

from .engine import run_investigation


@dataclass
class LegionResult:
    subject: str
    results: list
    merged_sources: list[dict]
    merged_report: str


class PhantomLegion:
    """Dispatch multiple investigators (workers) across targets.

    Modes:
    - parallel: run one investigator per subject concurrently
    - collaborative: run `num_agents` investigations on same subject concurrently and merge results

    Also supports a simple remote dispatch via SSH (best-effort stub using system `ssh`).
    """

    def __init__(self, max_workers: int = 4) -> None:
        self.max_workers = max_workers

    def _merge_ranked_sources(self, gathered_results: list, top_k: int = 20) -> tuple[list[dict], str]:
        # aggregated by URL: collect heuristic and learned scores, counts, titles, reasons
        agg: dict[str, dict] = {}
        for res in gathered_results:
            ranked = _pick(res, "ranked_sources", _pick(res, "ranked", [])) or []
            for item in ranked:
                url = _pick(item, "url")
                if not url:
                    continue
                entry = agg.setdefault(
                    url,
                    {
                        "scores": [],
                        "heuristics": [],
                        "learned": [],
                        "titles": set(),
                        "reasons": [],
                        "sources": [],
                        "kinds": set(),
                        "path_confidences": [],
                        "drift_scores": [],
                        "trail_depths": [],
                    },
                )
                score = float(_pick(item, "score", 0.0))
                heuristic_score = _pick(item, "heuristic_score")
                learned_score = _pick(item, "learned_score")
                path_confidence = float(_pick(item, "path_confidence", _trail_confidence(_pick(item, "trail_score", 0.0), _pick(item, "trail_strayed", False))) or 0.0)
                drift_score = float(_pick(item, "drift_score", _trail_drift(path_confidence, _pick(item, "trail_strayed", False))) or 0.0)
                trail_depth = int(_pick(item, "trail_depth", 0) or 0)
                entry["scores"].append(score)
                if heuristic_score is not None:
                    entry["heuristics"].append(float(heuristic_score))
                if learned_score is not None:
                    entry["learned"].append(float(learned_score))
                entry["path_confidences"].append(path_confidence)
                entry["drift_scores"].append(drift_score)
                entry["trail_depths"].append(trail_depth)
                title = _pick(item, "title")
                if title:
                    entry["titles"].add(title)
                reason = _pick(item, "reason")
                if reason:
                    entry["reasons"].append(reason)
                src = _pick(item, "source")
                if src:
                    entry["sources"].append(src)
                kind = _pick(item, "kind")
                if kind:
                    entry["kinds"].add(kind)

        # compute aggregates
        rows = []
        for url, data in agg.items():
            avg_score = sum(data["scores"]) / len(data["scores"]) if data["scores"] else 0.0
            avg_heuristic = sum(data["heuristics"]) / len(data["heuristics"]) if data["heuristics"] else avg_score
            avg_learned = sum(data["learned"]) / len(data["learned"]) if data["learned"] else avg_score
            avg_path_confidence = sum(data["path_confidences"]) / len(data["path_confidences"]) if data["path_confidences"] else 0.0
            avg_drift_score = sum(data["drift_scores"]) / len(data["drift_scores"]) if data["drift_scores"] else 0.0
            avg_trail_depth = sum(data["trail_depths"]) / len(data["trail_depths"]) if data["trail_depths"] else 0.0
            freq = len(data["scores"])
            weight = (0.5 * avg_score) + (0.3 * avg_heuristic) + (0.2 * avg_learned)
            weight = weight * (1 + min(freq - 1, 4) * 0.08)
            rows.append({"url": url, "avg_score": avg_score, "avg_heuristic": avg_heuristic, "avg_learned": avg_learned, "avg_path_confidence": avg_path_confidence, "avg_drift_score": avg_drift_score, "avg_trail_depth": avg_trail_depth, "freq": freq, "weight": weight, "titles": list(data["titles"]), "reasons": data["reasons"], "sources": data["sources"], "kinds": list(data["kinds"])})

        rows.sort(key=lambda r: (r["weight"], r["avg_score"]), reverse=True)
        lines = ["# PHANTOM_LEGION Merged Sources\n"]
        for r in rows[:top_k]:
            lines.append(f"- {r['url']} (score={r['weight']:.2f}, avg={r['avg_score']:.2f}, path={r['avg_path_confidence']:.1f}, drift={r['avg_drift_score']:.1f}, depth={r['avg_trail_depth']:.1f}, freq={r['freq']})")
            if r["kinds"]:
                lines.append(f"  - kinds: {', '.join(sorted(r['kinds']))}")
            if r["titles"]:
                lines.append(f"  - titles: {', '.join(r['titles'])}")
            if r["reasons"]:
                lines.append(f"  - excerpts: {r['reasons'][:2]}")
        if not rows:
            # fallback to join raw reports if no ranked items were found
            texts = [_pick(r, "report", "") for r in gathered_results]
            joined = "\n\n--- Fallback Reports ---\n\n".join([t for t in texts if t])
            # attempt to extract URLs from textual reports and present them
            urls = []
            for t in texts:
                if not t:
                    continue
                found = re.findall(r"https?://[\w\-./?&=%#]+", t)
                urls.extend(found)
            if urls:
                uniq = []
                seen = set()
                for u in urls:
                    if u not in seen:
                        seen.add(u)
                        uniq.append(u)
                lines = ["# PHANTOM_LEGION Merged Sources (extracted from reports)\n"]
                for u in uniq:
                    lines.append(f"- {u}")
                return [], "\n".join(lines)
            return [], joined or "# PHANTOM_LEGION Merged Sources\n"
        return rows[:top_k], "\n".join(lines)

    def dispatch_workers(
        self,
        subjects: Iterable[str],
        worker_urls: Iterable[str],
        *,
        num_agents: int = 1,
        mode: str = "parallel",
        top_k: int = 20,
        timeout: int = 300,
        **investigate_kwargs,
    ) -> List[LegionResult]:
        worker_urls = [url.rstrip("/") for url in worker_urls if url]
        subjects = list(subjects)
        if not worker_urls:
            raise ValueError("worker_urls must not be empty")
        if mode not in {"parallel", "collaborative"}:
            raise ValueError("mode must be 'parallel' or 'collaborative'")

        results: list[LegionResult] = []

        def _run_one(subject: str, worker_url: str) -> dict:
            payload = {"subject": subject, "top_k": top_k, "timeout": timeout, **investigate_kwargs}
            return _invoke_http_worker(worker_url, payload, timeout=timeout)

        if mode == "parallel":
            with ThreadPoolExecutor(max_workers=min(self.max_workers, max(1, len(subjects)))) as ex:
                futures = {}
                for index, subject in enumerate(subjects):
                    worker_url = worker_urls[index % len(worker_urls)]
                    futures[ex.submit(_run_one, subject, worker_url)] = subject
                for fut in as_completed(futures):
                    subject = futures[fut]
                    try:
                        res = fut.result()
                        merged_sources, merged = self._merge_ranked_sources([res], top_k=top_k)
                        results.append(LegionResult(subject=subject, results=[res], merged_sources=merged_sources, merged_report=merged))
                    except Exception as exc:
                        results.append(LegionResult(subject=subject, results=[{"error": str(exc)}], merged_sources=[], merged_report=""))
            return results

        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            for subject in subjects:
                futures = [ex.submit(_run_one, subject, worker_url) for worker_url in worker_urls[: max(1, num_agents)]]
                gathered = []
                for fut in as_completed(futures):
                    try:
                        gathered.append(fut.result())
                    except Exception as exc:
                        gathered.append({"error": str(exc)})
                merged_sources, merged_report = self._merge_ranked_sources(gathered, top_k=top_k)
                results.append(LegionResult(subject=subject, results=gathered, merged_sources=merged_sources, merged_report=merged_report))
        return results

    def dispatch_cluster(
        self,
        subjects: Iterable[str],
        coordinator_url: str,
        *,
        token: str,
        top_k: int = 20,
        timeout: int = 300,
        poll_interval: float = 1.0,
        **investigate_kwargs,
    ) -> List[LegionResult]:
        coordinator_url = coordinator_url.rstrip("/")
        subjects = list(subjects)
        job_ids: list[tuple[str, str]] = []
        for subject in subjects:
            payload = {"subject": subject, **investigate_kwargs}
            response = _post_json(f"{coordinator_url}/enqueue", payload, token=token, timeout=timeout)
            job_ids.append((subject, str(response.get("job_id", ""))))

        results: list[LegionResult] = []
        for subject, job_id in job_ids:
            if not job_id:
                results.append(LegionResult(subject=subject, results=[{"error": "missing job_id"}], merged_sources=[], merged_report=""))
                continue
            job = _wait_for_job(f"{coordinator_url}/job/{job_id}", token=token, timeout=timeout, poll_interval=poll_interval)
            if job.get("status") == "failed":
                results.append(LegionResult(subject=subject, results=[job], merged_sources=[], merged_report=str(job.get("error", ""))))
                continue
            result_payload = job.get("result") or {}
            merged_sources, merged_report = self._merge_ranked_sources([result_payload], top_k=top_k)
            if not merged_sources:
                merged_report = str(result_payload.get("report", ""))
            results.append(LegionResult(subject=subject, results=[result_payload], merged_sources=merged_sources, merged_report=merged_report))
        return results

    def dispatch(self, subjects: Iterable[str], *, num_agents: int = 1, mode: str = "parallel", top_k: int = 20, **investigate_kwargs) -> List[LegionResult]:
        subjects = list(subjects)
        if mode not in {"parallel", "collaborative"}:
            raise ValueError("mode must be 'parallel' or 'collaborative'")

        results: list[LegionResult] = []
        if mode == "parallel":
            with ThreadPoolExecutor(max_workers=min(self.max_workers, max(1, len(subjects)))) as ex:
                futures = {ex.submit(run_investigation, subject, **investigate_kwargs): subject for subject in subjects}
                for fut in as_completed(futures):
                    subject = futures[fut]
                    try:
                        res = fut.result()
                        merged_sources, merged = self._merge_ranked_sources([res], top_k=top_k)
                        results.append(LegionResult(subject=subject, results=[res], merged_sources=merged_sources, merged_report=merged))
                    except Exception as exc:
                        results.append(LegionResult(subject=subject, results=[{"error": str(exc)}], merged_sources=[], merged_report=""))
            return results

        # collaborative mode: run num_agents investigations for each subject concurrently and merge
        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            for subject in subjects:
                futures = [ex.submit(run_investigation, subject, **investigate_kwargs) for _ in range(num_agents)]
                gathered = []
                for fut in as_completed(futures):
                    try:
                        r = fut.result()
                        gathered.append(r)
                    except Exception as exc:
                        gathered.append({"error": str(exc)})
                merged_sources, merged_report = self._merge_ranked_sources(gathered, top_k=top_k)
                results.append(LegionResult(subject=subject, results=gathered, merged_sources=merged_sources, merged_report=merged_report))
        return results

    def dispatch_remote(self, subjects: Iterable[str], hosts: Iterable[str], *, ssh_user: Optional[str] = None, remote_cmd: Optional[str] = None, timeout: int = 300) -> List[LegionResult]:
        """Dispatch investigations remotely using system `ssh` to each host.

        This is a best-effort utility: it runs `ssh host 'remote_cmd'` for each (subject, host).
        `remote_cmd` may contain `{subject}` placeholder.
        """
        hosts = list(hosts)
        results: list[LegionResult] = []
        for subject in subjects:
            gathered = []
            for host in hosts:
                target = f"{ssh_user}@{host}" if ssh_user else host
                cmd = (remote_cmd or "python -m osint_agent.cli investigate {subject}").format(subject=_shell_quote(subject))
                full = ["ssh", target, cmd]
                try:
                    proc = subprocess.run(full, capture_output=True, text=True, timeout=timeout, check=False)
                    gathered.append({"host": host, "stdout": proc.stdout, "stderr": proc.stderr, "returncode": proc.returncode})
                except Exception as exc:
                    gathered.append({"host": host, "error": str(exc)})
            # merge remote textual outputs
            merged_sources, merged_report = self._merge_ranked_sources(gathered, top_k=10)
            if not merged_sources:
                stdout_text = "\n\n--- Remote Results ---\n\n".join([g.get("stdout", "") if isinstance(g, dict) else "" for g in gathered])
                if stdout_text.strip():
                    urls = re.findall(r"https?://[\w\-./?&=%#]+", stdout_text)
                    if urls:
                        lines = ["# PHANTOM_LEGION Remote Sources\n"] + [f"- {url}" for url in dict.fromkeys(urls)]
                        merged_report = "\n".join(lines)
                    elif not merged_report.strip() or merged_report.strip() == "# PHANTOM_LEGION Merged Sources":
                        merged_report = stdout_text
            elif not merged_report.strip():
                merged_report = "\n\n--- Remote Results ---\n\n".join([g.get("stdout", "") if isinstance(g, dict) else "" for g in gathered])
            results.append(LegionResult(subject=subject, results=gathered, merged_sources=merged_sources, merged_report=merged_report))
        return results


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _pick(item, attr: str, default=None):
    if isinstance(item, dict):
        return item.get(attr, default)
    return getattr(item, attr, default)


def _trail_confidence(trail_score, trail_strayed) -> float:
    score = float(trail_score or 0.0)
    confidence = max(0.0, min(100.0, score * 5.0))
    if trail_strayed:
        confidence = max(0.0, confidence - 15.0)
    return confidence


def _trail_drift(path_confidence, trail_strayed) -> float:
    drift = max(0.0, min(100.0, 100.0 - float(path_confidence or 0.0)))
    if trail_strayed:
        drift = min(100.0, drift + 15.0)
    return drift


def _invoke_http_worker(worker_url: str, payload: dict, timeout: int = 300) -> dict:
    endpoint = urljoin(worker_url.rstrip("/") + "/", "dispatch")
    data = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(endpoint, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib_request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"worker request to {endpoint} failed: {exc}") from exc


def _post_json(url: str, payload: dict, *, token: str, timeout: int = 300) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(url, data=data, headers={"Content-Type": "application/json", "X-Phantom-Token": token}, method="POST")
    try:
        with urllib_request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"request to {url} failed: {exc}") from exc


def _get_json(url: str, *, token: str, timeout: int = 300) -> dict:
    req = urllib_request.Request(url, headers={"X-Phantom-Token": token}, method="GET")
    try:
        with urllib_request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"request to {url} failed: {exc}") from exc


def _wait_for_job(url: str, *, token: str, timeout: int = 300, poll_interval: float = 1.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = _get_json(url, token=token, timeout=timeout)
        if job.get("status") in {"done", "failed"}:
            return job
        time.sleep(poll_interval)
    raise TimeoutError(f"timed out waiting for job at {url}")
