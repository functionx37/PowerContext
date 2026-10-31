"""SmartStudy: study records stored and recalled through real PowerContext APIs."""

import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import quote

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
POWERCONTEXT_URL = os.getenv("POWERCONTEXT_URL", "http://127.0.0.1:8000").rstrip("/")
POWERCONTEXT_TOKEN = os.getenv("POWERCONTEXT_TOKEN", "")
# This may be an existing Scope ID OR a stable key for creating one.
SCOPE_ID = os.getenv("POWERCONTEXT_SCOPE_ID", "smartstudy-default")
KIND = "study-session"
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    headers = {"Authorization": f"Bearer {POWERCONTEXT_TOKEN}"} if POWERCONTEXT_TOKEN else {}
    async with httpx.AsyncClient(base_url=POWERCONTEXT_URL, headers=headers, timeout=30, trust_env=False) as client:
        app.state.pc = client
        app.state.scope_id = None
        app.state.scope_lock = asyncio.Lock()
        yield


app = FastAPI(title="SmartStudy - 智能学习教练", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class StudyRecord(BaseModel):
    topic: str = Field(min_length=1, max_length=200, description="学习主题")
    duration_minutes: int = Field(ge=1, le=600, description="学习时长（分钟）")
    notes: str = Field("", max_length=2200, description="学习笔记")
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    confidence: int = Field(5, ge=1, le=10)

    @field_validator("topic")
    @classmethod
    def validate_topic(cls, value):
        value = value.strip()
        if not value or "\n" in value or "\r" in value:
            raise ValueError("请填写单行学习主题")
        return value


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8192, pattern=r"\S")
    limit: int = Field(10, ge=1, le=50)


class ReviewRequest(MemorySearchRequest):
    pass


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8192, pattern=r"\S")


async def _pc_request(method, path, payload=None, *, allow_missing=False):
    try:
        response = await app.state.pc.request(method, path, json=payload)
        if allow_missing and response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Expected an object")
        return data
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        logger.warning("PowerContext %s returned HTTP %s", path, status)
        detail = "PowerContext 认证失败，请检查 POWERCONTEXT_TOKEN。" if status in (401, 403) else (
            f"PowerContext 请求失败（HTTP {status}，{path}），请检查服务日志。"
        )
        raise HTTPException(503 if status >= 500 else 502, detail) from error
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(503, "PowerContext 服务不可用或响应无效，请检查服务地址与运行日志。") from error


async def _ensure_scope():
    if app.state.scope_id:
        return app.state.scope_id
    async with app.state.scope_lock:
        if app.state.scope_id:
            return app.state.scope_id
        scope = await _pc_request("GET", f"/v1/scopes/{quote(SCOPE_ID, safe='')}", allow_missing=True)
        if scope is None:
            scope = await _pc_request("POST", "/v1/scopes", {
                "title": "SmartStudy 学习记录", "summary": "智能学习教练的用户学习数据空间",
                "idempotency_key": SCOPE_ID,
            })
        if not isinstance(scope.get("scope_id"), str) or not scope["scope_id"]:
            raise HTTPException(503, "PowerContext 未返回有效的数据空间 ID。")
        app.state.scope_id = scope["scope_id"]
        return app.state.scope_id


async def _remember(text, reason):
    result = await _pc_request("POST", "/v1/memory/remember", {
        "scope_id": await _ensure_scope(), "kind": KIND, "text": text, "reason": reason,
    })
    if not result.get("records"):
        raise HTTPException(503, "PowerContext 未返回记忆引用，无法确认保存成功。")
    return result


async def _search_memory(query, limit=10):
    result = await _pc_request("POST", "/v1/memory/search", {
        "scope_id": await _ensure_scope(), "query": query, "limit": limit, "mode": "auto",
    })
    if not isinstance(result.get("hits"), list):
        raise HTTPException(503, "PowerContext 检索响应无效。")
    return result


async def _prepare_context(query, max_bytes=8000):
    result = await _pc_request("POST", "/v1/context/prepare", {
        "scope_id": await _ensure_scope(), "query": query, "max_bytes": max_bytes,
        "assembly": {"sections": [{"family": "memory", "limit": 8}]},
    })
    if result.get("status") not in ("ready", "empty"):
        raise HTTPException(503, "PowerContext 上下文响应无效。")
    # Preserve the complete server-rendered text, citations and byte boundaries.
    return result.get("content") or ""


def _study_fields(text):
    # Parse only the record header. Notes may themselves contain labels or colons.
    header = text.split("\n笔记:", 1)[0]
    def field(label):
        match = re.search(r"(?:^|\n)(?:\[[^\]\n]+\]\s*)?" + label + r":\s*([^\n]*)", header)
        return match.group(1).strip() if match else ""
    timestamp = re.match(r"\[([^\]]+)\]", header)
    duration = re.match(r"(\d+)", field("时长"))
    confidence = re.match(r"(\d+)", field("掌握程度"))
    return {
        "topic": field("学习主题"),
        "duration_minutes": int(duration.group(1)) if duration else 0,
        "confidence": int(confidence.group(1)) if confidence else None,
        "created_at": timestamp.group(1) if timestamp else "",
    }


async def _list_memories():
    scope_id = await _ensure_scope()
    entries, cursor, seen = [], None, set()
    while True:
        page = await _pc_request("POST", "/v1/atomic-memory/list", {
            "scope_id": scope_id, "kind": KIND, "states": ["active"], "limit": 100, "cursor": cursor,
        })
        if not isinstance(page.get("items"), list):
            raise HTTPException(503, "PowerContext 历史响应无效。")
        entries.extend(page["items"])
        cursor = page.get("next_cursor")
        if not cursor:
            break
        if cursor in seen:
            raise HTTPException(503, "PowerContext 返回了重复分页游标。")
        seen.add(cursor)
    return sorted(entries, key=lambda entry: _study_fields(entry.get("text", ""))["created_at"], reverse=True)


@app.get("/api/health")
async def health():
    try:
        await _pc_request("GET", "/health/ready")
        scope_id = await _ensure_scope()
        return {"status": "ok", "powercontext": "connected", "scope_id": scope_id}
    except HTTPException as error:
        return {"status": "degraded", "powercontext": "disconnected", "scope_id": None, "detail": error.detail}


@app.post("/api/study/record")
async def add_study_record(record: StudyRecord):
    now = datetime.now(timezone.utc).isoformat()
    text = (
        f"[{now}] 学习主题: {record.topic}\n时长: {record.duration_minutes} 分钟\n"
        f"难度: {record.difficulty}\n掌握程度: {record.confidence}/10\n笔记: {record.notes}"
    )
    if len(text.encode("utf-8")) > 8192:
        raise HTTPException(422, "学习记录超过 8192 字节，请缩短笔记。")
    result = await _remember(text, f"记录用户学习 {record.topic} 的情况")
    return {"success": True, "message": f"已记录学习: {record.topic} ({record.duration_minutes}分钟)",
            "powercontext_result": result}


@app.post("/api/study/search")
async def search_study_memories(req: MemorySearchRequest):
    results = await _search_memory(req.query, req.limit)
    context = await _prepare_context(req.query)
    return {"query": req.query, "hits": results["hits"], "context": context}


@app.post("/api/study/review")
async def get_review_suggestions(req: ReviewRequest):
    results = await _search_memory(req.query, req.limit)
    context = await _prepare_context(req.query, max_bytes=12000)
    topics = []
    for hit in results["hits"]:
        memory = hit["memory"]
        fields = _study_fields(memory["text"])
        if memory.get("kind") == KIND and fields["topic"]:
            topics.append({**fields, "score": hit["score"], "text_preview": memory["text"][:200],
                           "memory_ref": memory["artifact"]})
    return {"query": req.query, "related_topics": topics, "context_summary": context,
            "total_memories_found": len(topics)}


@app.get("/api/study/history")
async def get_study_history(limit: int = Query(50, ge=1, le=1000)):
    entries = await _list_memories()
    records = [{"id": entry["artifact"]["artifact_id"], "memory_ref": entry["artifact"],
                "text": entry["text"], "kind": entry["kind"], **_study_fields(entry["text"])}
               for entry in entries[:limit]]
    return {"records": records, "total": len(entries)}


@app.post("/api/chat")
async def chat_with_context(req: ChatRequest):
    context = await _prepare_context(req.message)
    results = await _search_memory(req.message, limit=5)
    memories = [hit["memory"] for hit in results["hits"] if hit["memory"].get("kind") == KIND]
    overview = any(phrase in req.message for phrase in ("学过哪些", "学习概况", "所有学习", "学习记录"))
    if not memories and overview:
        memories = (await _list_memories())[:5]
    related = [memory["text"] for memory in memories]
    return {"user_message": req.message, "retrieved_context": context or "暂无相关学习记录",
            "related_memories": related, "memory_refs": [memory["artifact"] for memory in memories],
            "suggestion": _generate_suggestion(req.message, context, related)}


def _generate_suggestion(message, context, memories):
    if not memories:
        return f"未找到关于「{message}」的学习记录，请先记录相关学习内容。"
    fields = [_study_fields(text) for text in memories]
    topics = "、".join(dict.fromkeys(item["topic"] for item in fields if item["topic"]))
    weakest = min(fields, key=lambda item: item["confidence"] if item["confidence"] is not None else 11)
    advice = (f"建议优先复习「{weakest['topic']}」（掌握程度 {weakest['confidence']}/10），结合笔记做练习。"
              if weakest["confidence"] is not None else "建议结合笔记进行复习和练习。")
    return f"根据你的学习记录，找到 {len(memories)} 条相关内容：{topics}。{advice}"


@app.get("/api/stats")
async def get_study_stats():
    entries = await _list_memories()
    topics, total_minutes = {}, 0
    for entry in entries:
        fields = _study_fields(entry["text"])
        total_minutes += fields["duration_minutes"]
        if fields["topic"]:
            topics[fields["topic"]] = topics.get(fields["topic"], 0) + 1
    return {"total_sessions": len(entries), "total_minutes": total_minutes, "unique_topics": len(topics),
            "top_topics": sorted(topics.items(), key=lambda item: item[1], reverse=True)[:10]}


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
async def serve_index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8080)
