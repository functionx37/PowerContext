"""SmartStudy - 智能学习教练后端服务器

基于 FastAPI 构建，集成 PowerContext 实现学习记忆与上下文管理。
"""

import os
import uuid
from datetime import datetime
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

load_dotenv()

POWERCONTEXT_URL = os.getenv("POWERCONTEXT_URL", "http://127.0.0.1:8000")
POWERCONTEXT_TOKEN = os.getenv("POWERCONTEXT_TOKEN", "")
SCOPE_ID = os.getenv("POWERCONTEXT_SCOPE_ID", "smartstudy-default")

pc_client: httpx.AsyncClient | None = None


def _pc_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if POWERCONTEXT_TOKEN:
        headers["Authorization"] = f"Bearer {POWERCONTEXT_TOKEN}"
    return headers


async def _ensure_scope():
    assert pc_client is not None
    try:
        resp = await pc_client.get(
            f"/v1/scopes/{SCOPE_ID}", headers=_pc_headers()
        )
        if resp.status_code == 200:
            return
    except Exception:
        pass

    try:
        await pc_client.post(
            "/v1/scopes",
            headers=_pc_headers(),
            json={
                "title": "SmartStudy 学习记录",
                "summary": "智能学习教练的用户学习数据空间",
                "idempotency_key": SCOPE_ID,
            },
        )
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pc_client
    pc_client = httpx.AsyncClient(base_url=POWERCONTEXT_URL, timeout=30.0)
    await _ensure_scope()
    yield
    await pc_client.aclose()


app = FastAPI(title="SmartStudy - 智能学习教练", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Request / Response Models ---

class StudyRecord(BaseModel):
    topic: str = Field(..., description="学习主题")
    duration_minutes: int = Field(..., ge=1, description="学习时长（分钟）")
    notes: str = Field("", description="学习笔记")
    difficulty: str = Field("medium", description="难度: easy/medium/hard")
    confidence: int = Field(5, ge=1, le=10, description="掌握程度 1-10")

class ReviewRequest(BaseModel):
    query: str = Field(..., description="复习查询内容")
    limit: int = Field(10, ge=1, le=50)

class ChatRequest(BaseModel):
    message: str = Field(..., description="用户消息")

class MemorySearchRequest(BaseModel):
    query: str = Field(..., description="搜索关键词")
    limit: int = Field(10, ge=1, le=50)


# --- PowerContext Integration ---

async def _remember(text: str, kind: str, reason: str = ""):
    assert pc_client is not None
    resp = await pc_client.post(
        "/v1/memory/remember",
        headers=_pc_headers(),
        json={
            "scope_id": SCOPE_ID,
            "kind": kind,
            "text": text,
            "reason": reason,
        },
    )
    if resp.status_code != 200:
        raise HTTPException(502, f"PowerContext remember failed: {resp.text}")
    return resp.json()

async def _search_memory(query: str, limit: int = 10):
    assert pc_client is not None
    resp = await pc_client.post(
        "/v1/memory/search",
        headers=_pc_headers(),
        json={
            "scope_id": SCOPE_ID,
            "query": query,
            "limit": limit,
            "mode": "auto",
        },
    )
    if resp.status_code != 200:
        return {"hits": []}
    return resp.json()

async def _prepare_context(query: str, max_bytes: int = 8000):
    assert pc_client is not None
    resp = await pc_client.post(
        "/v1/context/prepare",
        headers=_pc_headers(),
        json={
            "scope_id": SCOPE_ID,
            "query": query,
            "max_bytes": max_bytes,
        },
    )
    if resp.status_code != 200:
        return {"context": ""}
    return resp.json()

async def _list_memories(kind: str | None = None, limit: int = 50):
    assert pc_client is not None
    body: dict = {"scope_id": SCOPE_ID, "limit": limit}
    if kind:
        body["kind"] = kind
    resp = await pc_client.post(
        "/v1/memory/entries/list",
        headers=_pc_headers(),
        json=body,
    )
    if resp.status_code != 200:
        return {"entries": []}
    return resp.json()


# --- API Routes ---

@app.get("/api/health")
async def health():
    pc_status = "disconnected"
    if pc_client:
        try:
            r = await pc_client.get("/health/live", headers=_pc_headers())
            if r.status_code == 200:
                pc_status = "connected"
        except Exception:
            pc_status = "error"
    return {"status": "ok", "powercontext": pc_status, "scope_id": SCOPE_ID}


@app.post("/api/study/record")
async def add_study_record(record: StudyRecord):
    now = datetime.now().isoformat()
    text = (
        f"[{now}] 学习主题: {record.topic}\n"
        f"时长: {record.duration_minutes} 分钟\n"
        f"难度: {record.difficulty}\n"
        f"掌握程度: {record.confidence}/10\n"
        f"笔记: {record.notes}"
    )
    result = await _remember(
        text=text,
        kind="study-session",
        reason=f"记录用户学习 {record.topic} 的情况",
    )
    return {
        "success": True,
        "message": f"已记录学习: {record.topic} ({record.duration_minutes}分钟)",
        "powercontext_result": result,
    }


@app.post("/api/study/search")
async def search_study_memories(req: MemorySearchRequest):
    results = await _search_memory(req.query, req.limit)
    context = await _prepare_context(req.query)
    return {
        "query": req.query,
        "hits": results.get("hits", []),
        "context": context.get("context", ""),
    }


@app.post("/api/study/review")
async def get_review_suggestions(req: ReviewRequest):
    search_results = await _search_memory(req.query, req.limit)
    context_data = await _prepare_context(
        f"复习建议: {req.query}", max_bytes=12000
    )

    hits = search_results.get("hits", [])
    topics = []
    for hit in hits:
        memory = hit.get("memory", {})
        text = memory.get("text", "")
        if "学习主题:" in text:
            topic_line = text.split("\n")[0]
            topics.append({
                "topic": topic_line.replace("[", "").split("]")[1] if "]" in topic_line else topic_line,
                "score": hit.get("score", 0),
                "text_preview": text[:200],
            })

    return {
        "query": req.query,
        "related_topics": topics,
        "context_summary": context_data.get("context", "")[:500],
        "total_memories_found": len(hits),
    }


@app.get("/api/study/history")
async def get_study_history(limit: int = 50):
    results = await _list_memories(kind="study-session", limit=limit)
    entries = results.get("entries", [])

    records = []
    for entry in entries:
        records.append({
            "id": entry.get("artifact_id", entry.get("id", "")),
            "text": entry.get("text", ""),
            "created_at": entry.get("created_at", ""),
            "kind": entry.get("kind", ""),
        })

    return {"records": records, "total": len(records)}


@app.post("/api/chat")
async def chat_with_context(req: ChatRequest):
    context_data = await _prepare_context(req.message)
    search_results = await _search_memory(req.message, limit=5)

    context_text = context_data.get("context", "")
    hits = search_results.get("hits", [])

    related_info = []
    for hit in hits:
        memory = hit.get("memory", {})
        related_info.append(memory.get("text", "")[:300])

    return {
        "user_message": req.message,
        "retrieved_context": context_text[:1000] if context_text else "暂无相关学习记录",
        "related_memories": related_info[:3],
        "suggestion": _generate_suggestion(req.message, context_text, related_info),
    }


def _generate_suggestion(message: str, context: str, memories: list) -> str:
    if not memories and not context:
        return f"你还没有关于「{message}」的学习记录。建议开始学习相关内容，我会帮你记住进度！"

    memory_count = len(memories)
    return (
        f"根据你的学习记录，我找到了 {memory_count} 条相关内容。"
        f"建议复习之前的笔记，重点关注掌握程度较低的部分。"
        f"坚持每天复习，记忆效果会更好！"
    )


@app.get("/api/stats")
async def get_study_stats():
    results = await _list_memories(kind="study-session", limit=200)
    entries = results.get("entries", [])

    total_sessions = len(entries)
    total_minutes = 0
    topics = {}

    for entry in entries:
        text = entry.get("text", "")
        for line in text.split("\n"):
            if "时长:" in line:
                try:
                    mins = int(line.split(":")[1].strip().split(" ")[0])
                    total_minutes += mins
                except (ValueError, IndexError):
                    pass
            if "学习主题:" in line:
                topic = line.split("学习主题:")[1].strip()
                topics[topic] = topics.get(topic, 0) + 1

    return {
        "total_sessions": total_sessions,
        "total_minutes": total_minutes,
        "unique_topics": len(topics),
        "top_topics": sorted(topics.items(), key=lambda x: x[1], reverse=True)[:10],
    }


# --- Serve Frontend ---

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    async def serve_index():
        return FileResponse(os.path.join(static_dir, "index.html"))

    @app.get("/favicon.ico")
    async def favicon():
        return FileResponse(os.path.join(static_dir, "favicon.ico"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8080, reload=True)
