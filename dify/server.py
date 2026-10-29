"""Trusted single-worker HTTP bridge; all durable game state lives in PowerContext."""
import asyncio
import hashlib
import json
import os
import secrets
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from game import describe, initial_state, normalize, transition

PC_URL = os.getenv("POWERCONTEXT_URL", "http://127.0.0.1:8000").rstrip("/")
PC_TOKEN = os.getenv("POWERCONTEXT_TOKEN", "")
BRIDGE_TOKEN = os.getenv("SHOP_API_KEY", "")
KIND = "shop-turn-v1"
PREFIX = "记仇杂货铺状态快照 v1\n"
lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app):
    if len(BRIDGE_TOKEN) < 16:
        raise RuntimeError("请将 SHOP_API_KEY 设为至少 16 字符的随机字符串。")
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        app.state.pc = client
        yield


app = FastAPI(title="记仇杂货铺 · PowerContext Bridge", version="1.0.0", lifespan=lifespan)


class TurnInput(BaseModel):
    player_id: str = Field(min_length=1, max_length=48)
    action: str
    line: str = Field(default="", max_length=300)
    request_id: str = Field(min_length=1, max_length=80)


class CommitInput(TurnInput):
    expected_turn: int
    state: dict
    event: str
    narrative: str


def authorize(key):
    if not key or not secrets.compare_digest(key, BRIDGE_TOKEN):
        raise HTTPException(401, "需要有效的 X-Shop-Key。")


async def pc(path, payload=None):
    headers = {"Authorization": "Bearer " + PC_TOKEN} if PC_TOKEN else {}
    try:
        r = await app.state.pc.request("POST" if payload is not None else "GET",
                                       PC_URL + path, json=payload, headers=headers)
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError) as error:
        # Fail closed: no simulated success or fallback local database.
        raise HTTPException(503, "PowerContext 读写失败；本回合未确认，请查看服务日志后使用相同请求编号重试。") from error


async def load(player_id):
    key = hashlib.sha256(("grudge-shop-v1:" + player_id).encode()).hexdigest()
    scope = await pc("/v1/scopes", {"title": "记仇杂货铺 / " + player_id,
        "summary": "玩家显式选择的独立游戏存档。保存 NPC 关系、剧情与回合证据。",
        "idempotency_key": "grudge-shop-v1-" + key})
    scope_id = scope["scope_id"]
    items, cursor = [], None
    while True:
        page = await pc("/v1/atomic-memory/list", {"scope_id": scope_id, "kind": KIND,
                       "states": ["active"], "limit": 100, "cursor": cursor})
        items.extend(page["items"])
        cursor = page.get("next_cursor")
        if not cursor:
            break
    snapshots = []
    for record in items:
        if record["text"].startswith(PREFIX):
            try:
                snapshots.append((json.loads(record["text"][len(PREFIX):]), record["artifact"]))
            except (ValueError, KeyError) as error:
                raise HTTPException(503, "存档损坏，停止写入；请使用新玩家编号或检查 PowerContext 数据。") from error
    snapshots.sort(key=lambda pair: pair[0]["state"]["turn"])
    state = snapshots[-1][0]["state"] if snapshots else initial_state()
    return scope_id, state, snapshots


def checked(data):
    try:
        return normalize(data.player_id, data.action, data.line, data.request_id)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


def replay(snapshots, inp):
    for packet, artifact in snapshots:
        if packet["request_id"] == inp["request_id"]:
            if any(packet[k] != inp[k] for k in ("player_id", "action", "line")):
                raise HTTPException(409, "同一请求编号不能用于不同的行动或台词。")
            return packet, artifact
    return None


@app.get("/health")
async def health():
    await pc("/health/live")
    return {"status": "ok", "memory_backend": "powercontext", "version": "1.0.0"}


@app.post("/v1/turns/prepare")
async def prepare(data: TurnInput, x_shop_key: str = Header(default="")):
    authorize(x_shop_key)
    inp = checked(data)
    async with lock:
        scope_id, state, snapshots = await load(inp["player_id"])
        existing = replay(snapshots, inp)
        return {"input": inp, "state": state, "scope_id": scope_id,
                "recalled_turns": len(snapshots), "replay": existing[0] if existing else None,
                "memory_refs": [a for _, a in snapshots[-3:]]}


@app.post("/v1/turns/commit")
async def commit(data: CommitInput, x_shop_key: str = Header(default="")):
    authorize(x_shop_key)
    inp = checked(data)
    async with lock:
        scope_id, state, snapshots = await load(inp["player_id"])
        existing = replay(snapshots, inp)
        if existing:
            packet, artifact = existing
            return dict(packet, scope_id=scope_id, memory_ref=artifact, replayed=True)
        if state["turn"] != data.expected_turn:
            raise HTTPException(409, "同一玩家的存档已变化，请重新运行工作流。")
        try:
            next_state, event = transition(state, inp["action"], inp["line"])
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        if data.state != next_state or data.event != event or data.narrative != describe(next_state, event):
            raise HTTPException(422, "规则校验不通过，请重新生成并导入同版本 DSL。")
        packet = dict(inp, expected_turn=data.expected_turn, state=next_state,
                      event=event, narrative=data.narrative)
        text = PREFIX + json.dumps(packet, ensure_ascii=False, separators=(",", ":"))
        saved = await pc("/v1/memory/remember", {"scope_id": scope_id, "kind": KIND,
                         "text": text, "reason": "玩家确认游戏行动；保存规则裁决及下回合 NPC 记忆。"})
        if not saved.get("records"):
            raise HTTPException(503, "PowerContext 没有返回记忆引用，不能确认回合成功。")
        return dict(packet, scope_id=scope_id, memory_ref=saved["records"][0]["artifact"], replayed=False)
