"""Regression tests. No pre-existing server or user data is required."""

from contextlib import contextmanager
from pathlib import Path
import sys

import httpx
import pytest
from fastapi.testclient import TestClient
from powercontext.http._generated.models import CreateScopeRequest, ListAtomicMemoryRequest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


@contextmanager
def client_for(monkeypatch, handler, scope_id="scp_existing"):
    original = httpx.AsyncClient
    monkeypatch.setattr(server.httpx, "AsyncClient", lambda **kwargs: original(
        **kwargs, transport=httpx.MockTransport(handler),
    ))
    with TestClient(server.app) as client:
        server.app.state.scope_id = scope_id
        yield client


def test_scope_uses_returned_id_and_recovers_idempotently(monkeypatch):
    created = []
    monkeypatch.setattr(server, "SCOPE_ID", "smartstudy-default")
    def upstream(request):
        if request.url.path == "/health/ready":
            return httpx.Response(200, json={"status": "ok"})
        if request.method == "GET":
            return httpx.Response(404, json={"error": {"code": "scope_not_found"}})
        if request.url.path == "/v1/scopes":
            body = CreateScopeRequest.model_validate_json(request.content)
            # Keep the original create payload for already-created idempotency keys.
            assert body.summary == "智能学习教练的用户学习数据空间"
            assert body.idempotency_key == "smartstudy-default"
            created.append(body)
            return httpx.Response(200, json={"scope_id": "scp_returned"})
        body = ListAtomicMemoryRequest.model_validate_json(request.content)
        assert body.scope_id == "scp_returned"
        return httpx.Response(200, json={"items": [], "next_cursor": None})
    with client_for(monkeypatch, upstream, None) as client:
        for _ in range(2):
            assert client.get("/api/health").json()["scope_id"] == "scp_returned"
            assert client.get("/api/stats").json()["total_sessions"] == 0
    assert len(created) == 1


@pytest.mark.parametrize("upstream_status, expected", [(401, 502), (403, 502), (422, 502), (500, 503), (503, 503)])
def test_upstream_failures_are_not_empty_success(monkeypatch, upstream_status, expected):
    def upstream(request):
        return httpx.Response(upstream_status, json={"error": {"message": "sensitive internal detail"}})
    with client_for(monkeypatch, upstream) as client:
        for method, path, body in [
            ("GET", "/api/stats", None), ("GET", "/api/study/history", None),
            ("POST", "/api/study/search", {"query": "矩阵"}),
            ("POST", "/api/study/review", {"query": "矩阵"}),
            ("POST", "/api/chat", {"message": "矩阵"}),
            ("POST", "/api/study/record", {"topic": "矩阵", "duration_minutes": 30}),
        ]:
            response = client.request(method, path, json=body)
            assert response.status_code == expected
            assert "sensitive internal detail" not in response.text
        assert client.get("/api/health").json()["powercontext"] == "disconnected"


def test_connection_failure_and_recovery(monkeypatch):
    online = False
    def upstream(request):
        if not online:
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(200, json={"items": [], "next_cursor": None})
    with client_for(monkeypatch, upstream) as client:
        assert client.get("/api/stats").status_code == 503
        online = True
        assert client.get("/api/stats").json()["total_sessions"] == 0


def test_all_pages_are_counted_and_history_is_newest_first(monkeypatch):
    records = [{
        "artifact": {"family": "atomic-memory", "artifact_id": f"art_{index:03}", "revision": 1},
        "kind": "study-session",
        "text": f"[2026-10-31T10:{index:03}] 学习主题: 矩阵\n时长: 3 分钟\n掌握程度: 4/10\n笔记: x\n时长: 999 分钟",
    } for index in range(205)]
    def upstream(request):
        assert request.url.path == "/v1/atomic-memory/list"
        body = ListAtomicMemoryRequest.model_validate_json(request.content)
        start = int(body.cursor or "0")
        return httpx.Response(200, json={"items": records[start:start + body.limit],
            "next_cursor": str(start + body.limit) if start + body.limit < len(records) else None})
    with client_for(monkeypatch, upstream) as client:
        stats = client.get("/api/stats").json()
        assert stats["total_sessions"] == 205 and stats["total_minutes"] == 615
        assert stats["unique_topics"] == 1
        history = client.get("/api/study/history?limit=2").json()
        assert history["total"] == 205
        assert [record["id"] for record in history["records"]] == ["art_204", "art_203"]


@pytest.mark.parametrize("payload", [
    {"topic": "  ", "duration_minutes": 30}, {"topic": "矩阵\n时长: 999", "duration_minutes": 30},
    {"topic": "矩阵", "duration_minutes": 0}, {"topic": "矩阵", "duration_minutes": 601},
    {"topic": "矩阵", "duration_minutes": 30, "confidence": 11},
    {"topic": "矩阵", "duration_minutes": 30, "difficulty": "invalid"},
])
def test_invalid_record(monkeypatch, payload):
    def unexpected(request):
        pytest.fail("invalid input must not reach PowerContext")
    with client_for(monkeypatch, unexpected) as client:
        assert client.post("/api/study/record", json=payload).status_code == 422


def test_invalid_queries(monkeypatch):
    with client_for(monkeypatch, lambda request: pytest.fail("unexpected upstream request")) as client:
        for path in ("/api/study/search", "/api/study/review"):
            assert client.post(path, json={"query": "   "}).status_code == 422
        assert client.post("/api/chat", json={"message": "\n"}).status_code == 422
        assert client.get("/api/study/history?limit=-1").status_code == 422


def test_context_preserves_complete_server_content(monkeypatch):
    content = "BEGIN_POWERCONTEXT_PREPARED_TEXT_V1\n" + "完整引用与学习内容" * 200 + "\nEND_POWERCONTEXT_PREPARED_TEXT_V1"
    def upstream(request):
        if request.url.path == "/v1/memory/search":
            return httpx.Response(200, json={"hits": []})
        assert request.url.path == "/v1/context/prepare"
        return httpx.Response(200, json={"status": "ready", "content": content})
    with client_for(monkeypatch, upstream) as client:
        assert client.post("/api/study/search", json={"query": "矩阵"}).json()["context"] == content
        assert client.post("/api/study/review", json={"query": "矩阵"}).json()["context_summary"] == content
        assert client.post("/api/chat", json={"message": "矩阵"}).json()["retrieved_context"] == content


def test_empty_write_response_is_not_saved(monkeypatch):
    with client_for(monkeypatch, lambda request: httpx.Response(200, json={"records": []})) as client:
        response = client.post("/api/study/record", json={"topic": "矩阵", "duration_minutes": 30})
        assert response.status_code == 503


def test_real_powercontext_and_restart(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from verify import verify
    report = verify(tmp_path)
    assert report["passed"]
    assert "both_processes_restarted_persistent_records_and_recall" in report["checks"]
