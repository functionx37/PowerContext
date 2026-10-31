"""SmartStudy 接口测试

运行方式: pytest tests/test_server.py -v
需要后端服务运行中: python server.py
"""

import pytest
import httpx

BASE_URL = "http://127.0.0.1:8080"


@pytest.fixture
def client():
    return httpx.Client(base_url=BASE_URL, timeout=10.0)


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "powercontext" in data


def test_study_record(client):
    resp = client.post("/api/study/record", json={
        "topic": "测试 - 单元测试",
        "duration_minutes": 15,
        "difficulty": "easy",
        "confidence": 8,
        "notes": "这是一条测试记录",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "测试" in data["message"]


def test_study_search(client):
    resp = client.post("/api/study/search", json={
        "query": "测试",
        "limit": 5,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "hits" in data
    assert "context" in data


def test_study_review(client):
    resp = client.post("/api/study/review", json={
        "query": "单元测试",
        "limit": 5,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "related_topics" in data
    assert "total_memories_found" in data


def test_study_history(client):
    resp = client.get("/api/study/history")
    assert resp.status_code == 200
    data = resp.json()
    assert "records" in data
    assert "total" in data


def test_chat(client):
    resp = client.post("/api/chat", json={
        "message": "我学过哪些内容？",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "suggestion" in data
    assert "retrieved_context" in data


def test_stats(client):
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_sessions" in data
    assert "total_minutes" in data


def test_frontend_served(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "SmartStudy" in resp.text
