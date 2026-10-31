"""Exercise real HTTP APIs, then restart both services and verify persistence."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import uuid

import httpx

from run_local import ROOT, wait_ready


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@contextmanager
def running(runtime, scope_key):
    port, pc_port = free_port(), free_port()
    while port == pc_port:
        pc_port = free_port()
    runtime.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, POWERCONTEXT_SCOPE_ID=scope_key)
    with (runtime / "launcher.log").open("a", encoding="utf-8") as log:
        process = subprocess.Popen([
            sys.executable, str(ROOT / "tools" / "run_local.py"), "--port", str(port),
            "--pc-port", str(pc_port), "--data-dir", str(runtime),
        ], env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            wait_ready(f"http://127.0.0.1:{port}/api/health", process, timeout=90)
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30, trust_env=False) as client:
                yield client, f"http://127.0.0.1:{pc_port}"
        finally:
            (runtime / "stop-request").touch()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=10)


def request(client, method, path, payload=None):
    response = client.request(method, path, json=payload)
    response.raise_for_status()
    return response.json()


def verify(runtime):
    scope_key = "smartstudy-verify-" + uuid.uuid4().hex
    report = {"verified_at": datetime.now(timezone.utc).isoformat(),
              "powercontext_version": importlib.metadata.version("powercontext"),
              "python_version": sys.version.split()[0], "backend": "official-powercontext", "checks": []}
    with running(runtime, scope_key) as (client, pc_url):
        initial = request(client, "GET", "/api/health")
        assert initial["powercontext"] == "connected", initial
        assert initial["scope_id"] != scope_key
        assert request(client, "GET", "/api/stats")["total_sessions"] == 0
        empty = request(client, "POST", "/api/study/review", {"query": "矩阵"})
        assert empty["related_topics"] == [] and empty["context_summary"] == ""
        report["checks"].append("fresh_scope_and_empty_state")
        refs = []
        for topic, duration, confidence, notes in [
            ("线性代数 - 矩阵乘法", 45, 7, "需要注意矩阵维度匹配。\n时长: 999 分钟\n学习主题: 笔记中的示例标签"),
            ("线性代数 - 矩阵求逆", 30, 3, "矩阵求逆还不熟练，需要复习行变换。"),
        ]:
            saved = request(client, "POST", "/api/study/record", {
                "topic": topic, "duration_minutes": duration, "confidence": confidence,
                "difficulty": "medium", "notes": notes,
            })
            assert saved["success"]
            refs.append(saved["powercontext_result"]["records"][0]["artifact"])
        history = request(client, "GET", "/api/study/history?limit=1")
        assert history["total"] == 2 and len(history["records"]) == 1
        assert history["records"][0]["id"] == refs[1]["artifact_id"]
        stats = request(client, "GET", "/api/stats")
        assert (stats["total_sessions"], stats["total_minutes"], stats["unique_topics"]) == (2, 75, 2), stats
        report["checks"].append("record_history_stats_and_note_label_safety")
        search = request(client, "POST", "/api/study/search", {"query": "矩阵"})
        found = {hit["memory"]["artifact"]["artifact_id"] for hit in search["hits"]}
        assert found == {ref["artifact_id"] for ref in refs}
        review = request(client, "POST", "/api/study/review", {"query": "矩阵"})
        assert len(review["related_topics"]) == 2
        assert all(topic["topic"].startswith("线性代数") for topic in review["related_topics"])
        with httpx.Client(base_url=pc_url, timeout=30, trust_env=False) as pc:
            direct = request(pc, "POST", "/v1/context/prepare", {
                "scope_id": initial["scope_id"], "query": "矩阵", "max_bytes": 12000,
                "assembly": {"sections": [{"family": "memory", "limit": 8}]},
            })
            assert review["context_summary"] == direct["content"]
            assert len(direct["content"].encode("utf-8")) == direct["content_bytes"]
            for ref in refs:
                assert ref["artifact_id"] in direct["content"]
            stored = request(pc, "POST", "/v1/atomic-memory/list", {
                "scope_id": initial["scope_id"], "kind": "study-session", "states": ["active"],
            })
            assert {item["artifact"]["artifact_id"] for item in stored["items"]} == found
        report["checks"].append("real_search_review_and_complete_cited_context")
        chat = request(client, "POST", "/api/chat", {"message": "矩阵"})
        assert "矩阵求逆" in chat["suggestion"] and "3/10" in chat["suggestion"]
        assert len(chat["memory_refs"]) == 2
        overview = request(client, "POST", "/api/chat", {"message": "我学过哪些内容？"})
        assert overview["related_memories"]
        missing = request(client, "POST", "/api/chat", {"message": "zzznomatch123xyz"})
        assert missing["related_memories"] == []
        report["checks"].append("grounded_chat_overview_and_no_match")
        for path in ("/", "/static/app.js", "/static/style.css", "/favicon.ico"):
            assert client.get(path).is_success
        report["checks"].append("frontend_assets")
        report.update(scope_id=initial["scope_id"], memory_refs=refs, stats=stats,
                      context_bytes=direct["content_bytes"], suggestion=chat["suggestion"])
    # New processes, same official SQLite database and idempotency key.
    with running(runtime, scope_key) as (client, _):
        health = request(client, "GET", "/api/health")
        assert health["scope_id"] == initial["scope_id"]
        assert request(client, "GET", "/api/stats") == stats
        restored = request(client, "GET", "/api/study/history")
        assert {record["id"] for record in restored["records"]} == found
        review = request(client, "POST", "/api/study/review", {"query": "矩阵"})
        assert len(review["related_topics"]) == 2 and review["context_summary"]
        report["checks"].append("both_processes_restarted_persistent_records_and_recall")
    report["passed"] = True
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "evidence" / "verification.json")
    args = parser.parse_args()
    runtime = ROOT / ".runtime" / ("verify-" + uuid.uuid4().hex)
    report = verify(runtime)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: {len(report['checks'])} checks; report: {args.output}")


if __name__ == "__main__":
    main()
