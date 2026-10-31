# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Capture the original visible events of a selected Pi v3 session branch."""

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, JsonValue

from powercontext.sources.connectors import ConnectorRunCompletion, ConnectorRunStatus
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TextEvidence


class PiSessionInput(BaseModel):
    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


def _records(value):  # noqa: C901 - atomically validate the complete session graph
    def invalid_constant(value):
        raise ValueError(f"Invalid JSON constant: {value}")  # noqa: TRY003

    try:
        records = [
            json.loads(line, parse_constant=invalid_constant)
            for line in value.content.decode("utf-8-sig").splitlines()
            if line.strip()
        ]
    except (ValueError, UnicodeError) as error:
        raise ValueError("Invalid Pi JSONL") from error  # noqa: TRY003
    if not records or not isinstance(records[0], dict):
        raise ValueError("Missing session header")  # noqa: TRY003
    header = records[0]
    if header.get("type") != "session" or type(header.get("version")) is not int or header["version"] != 3:
        raise ValueError("Pi session version must be 3")  # noqa: TRY003
    if not isinstance(header.get("id"), str) or not header["id"].strip():
        raise ValueError("Missing session identity")  # noqa: TRY003
    nodes = {}
    for record in records[1:]:
        if not isinstance(record, dict):
            raise ValueError("Invalid Pi record")  # noqa: TRY003, TRY004 - public parse errors are ValueError
        identity = record.get("id")
        if not isinstance(identity, str) or not identity.strip() or identity in nodes or "parentId" not in record:
            raise ValueError("Invalid or duplicate event identity")  # noqa: TRY003
        parent = record["parentId"]
        if parent is not None and (not isinstance(parent, str) or parent not in nodes):
            raise ValueError("Parent must precede child")  # noqa: TRY003
        nodes[identity] = record
    if value.leaf_id is not None and value.leaf_id not in nodes:
        raise ValueError("Unknown leaf")  # noqa: TRY003
    return header["id"], nodes


def _body(content):
    if isinstance(content, str):
        return content
    parts = []
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif block.get("type") == "toolCall":
                arguments = json.dumps(
                    block.get("arguments", {}), ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                parts.append(f"[tool_call {block.get('name', '')} {block.get('id', '')}] {arguments}")
    return "\n".join(parts)


def parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]:
    session_id, nodes = _records(value)
    leaf = value.leaf_id if value.leaf_id is not None else next(reversed(nodes), None)
    chain = []
    while leaf is not None:
        record = nodes[leaf]
        chain.append(record)
        leaf = record["parentId"]
    events = []
    for record in reversed(chain):
        kind = record.get("type")
        role, body = "", ""
        if kind == "message":
            message = record.get("message", {})
            if not isinstance(message, dict):
                raise ValueError("Pi message must be an object")  # noqa: TRY003 - parse contract
            role = message.get("role", "")
            body = _body(message.get("content"))
            if role == "toolResult" and body:
                body = f"[tool_result {message.get('toolName', '')} {message.get('toolCallId', '')}] {body}"
            elif role == "bashExecution" and (message.get("command") or message.get("output")):
                body = f"$ {message.get('command', '')}\n{message.get('output', '')}"
        elif kind in ("compaction", "branch_summary"):
            role, body = kind, record.get("summary", "")
        elif kind == "custom_message":
            role, body = "custom", _body(record.get("content"))
        if body and role:
            events.append(
                PiEventInput(
                    session_id=session_id,
                    event_id=record["id"],
                    parent_id=record["parentId"],
                    event_type=kind,
                    role=role,
                    content=f"{role}: {body}",
                    record=record,
                )
            )
    return tuple(events)


class PiEventSource(Source):
    event: PiEventInput


class _PiProjection:
    name = "powercontext.text-evidence"
    version = "1"
    source_class = PiEventSource
    output_class = TextEvidence

    def project(self, source):
        event = source.event
        return TextEvidence(
            source_type="pi-event",
            source_id=source.name,
            content=event.content,
            metadata={k: getattr(event, k) for k in ("session_id", "event_id", "parent_id", "event_type", "role")},
        )


class _PiDefinition:
    name = "pi-event"
    version = "1"
    input_class = PiEventInput
    source_class = PiEventSource
    projections = (_PiProjection(),)

    async def resolve(self, value):
        digest = hashlib.sha256(json.dumps([value.session_id, value.event_id], ensure_ascii=False).encode()).hexdigest()
        return PiEventSource(name=f"pi:{digest}", materialization=SourceMaterialization.CAPTURED, event=value)

    async def read(self, source):
        return source.event


PI_EVENT_SOURCE_DEFINITION = _PiDefinition()


class PiSessionConnector:
    name = "pi-session-history"
    version = "1"
    source_definitions = frozenset({"pi-event"})

    def __init__(self, path, leaf_id=None):
        self.path = Path(path)
        self.leaf_id = leaf_id

    async def run(self, session):
        value = PiSessionInput(content=self.path.read_bytes(), leaf_id=self.leaf_id)
        events = parse_pi_session(value)
        session_id, records = _records(value)
        previous = session.checkpoint or {"session_id": session_id, "records": {}}
        if previous["session_id"] != session_id:
            raise ValueError("Session identity changed")  # noqa: TRY003
        hashes = {
            key: hashlib.sha256(
                json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            for key, record in records.items()
        }
        imported = dict(previous["records"])
        for key, digest in imported.items():
            if hashes.get(key) != digest:
                raise ValueError("Previously captured event changed or disappeared")  # noqa: TRY003
        for event in events:
            if event.event_id not in imported:
                await session.submit(event.event_id, "pi-event", event)
                imported[event.event_id] = hashes[event.event_id]
        return ConnectorRunCompletion(
            status=ConnectorRunStatus.COMPLETE, checkpoint={"session_id": session_id, "records": imported}
        )
