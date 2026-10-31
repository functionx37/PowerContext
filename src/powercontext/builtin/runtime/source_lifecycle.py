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

"""Durable evidence dependencies with retryable native availability propagation."""

import json

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import insert, select, update

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory.models import MemoryCitation
from powercontext.builtin.persistence.tables import SOURCE_LIFECYCLE_NODES_TABLE as NODES
from powercontext.builtin.runtime.models import GetMemoryEntryRequest
from powercontext.sources import SourceRef


class SourceLifecycleError(ValueError):
    """Invalid evidence binding, dependency or lifecycle transition."""


class SourceLifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    node_id: str
    reason: str
    revision: int = Field(gt=0)
    sequence: int = Field(gt=0)
    available: bool

    @field_validator("node_id", "reason")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Event strings must be nonempty")  # noqa: TRY003
        return value


class SourceLifecycleApplication:
    def __init__(self, runtime, database):
        self.runtime = runtime
        self.database = database

    def for_scope(self, scope_id):
        return ScopedSourceLifecycle(self.runtime, self.database, scope_id)


class ScopedSourceLifecycle:
    def __init__(self, runtime, database, scope_id):
        self.runtime, self.database, self.scope_id = runtime, database, scope_id

    async def _load(self):
        async with self.database.transaction() as connection:
            rows = (
                await connection.execute(
                    select(NODES.c.node_id, NODES.c.payload).where(NODES.c.scope_id == self.scope_id)
                )
            ).all()
        return {node: json.loads(payload) for node, payload in rows}

    async def _save(self, nodes, new=None):
        async with self.database.transaction() as connection:
            for identity, node in nodes.items():
                values = {
                    "kind": node["kind"],
                    "artifact_id": node["reference"].get("artifact_id"),
                    "available": node["available"],
                    "payload": json.dumps(node, ensure_ascii=False, separators=(",", ":")).encode(),
                }
                if identity == new:
                    await connection.execute(insert(NODES).values(scope_id=self.scope_id, node_id=identity, **values))
                else:
                    await connection.execute(
                        update(NODES)
                        .where(NODES.c.scope_id == self.scope_id, NODES.c.node_id == identity)
                        .values(**values)
                    )

    @staticmethod
    def _reference(node):
        cls = {"source": SourceRef, "memory": MemoryCitation, "topic": ArtifactRef}[node["kind"]]
        return cls.model_validate(node["reference"])

    @staticmethod
    def _states(nodes):
        visited = set()

        def visit(identity):
            if identity in visited:
                return nodes[identity]["available"]
            node = nodes[identity]
            if node["kind"] != "source":
                values = [visit(parent) for parent in node["parents"]]
                node["available"] = all(values) if node["policy"] == "all" else any(values)
            visited.add(identity)
            return node["available"]

        for identity in nodes:
            visit(identity)

    async def register_source(self, node_id, source_ref, *, revision):
        if type(revision) is not int or revision <= 0 or not isinstance(source_ref, SourceRef):
            raise SourceLifecycleError("Invalid Source registration")  # noqa: TRY003
        await self._register(node_id, "source", source_ref, (), "all", revision)

    async def register_memory(self, node_id, citation, *, parents, policy):
        if not isinstance(citation, MemoryCitation):
            raise SourceLifecycleError("Expected a Memory citation")  # noqa: TRY003
        await self._register(node_id, "memory", citation, parents, policy, None)

    async def register_topic(self, node_id, artifact_ref, *, parents, policy):
        if not isinstance(artifact_ref, ArtifactRef) or artifact_ref.family != "topic-memory":
            raise SourceLifecycleError("Expected a Topic Memory reference")  # noqa: TRY003
        await self._register(node_id, "topic", artifact_ref, parents, policy, None)

    async def _register(self, node_id, kind, reference, parents, policy, revision):  # noqa: C901 - one binding boundary
        if type(node_id) is not str or not node_id.strip() or len(node_id) > 256:
            raise SourceLifecycleError("Invalid node identity")  # noqa: TRY003
        if policy not in ("all", "any"):
            raise SourceLifecycleError("Unknown dependency policy")  # noqa: TRY003
        parents = tuple(parents)
        if any(type(parent) is not str or not parent.strip() for parent in parents):
            raise SourceLifecycleError("Parents must be node identities")  # noqa: TRY003
        if kind != "source" and (not parents or len(set(parents)) != len(parents) or node_id in parents):
            raise SourceLifecycleError("Invalid parents")  # noqa: TRY003
        parents = tuple(sorted(parents))
        async with self.runtime._scope_operation(self.scope_id), self.runtime._locked(self.scope_id):
            nodes = await self._load()
            if any(parent not in nodes for parent in parents):
                raise SourceLifecycleError("Parents must already be registered")  # noqa: TRY003
            node = {
                "kind": kind,
                "reference": reference.model_dump(mode="json"),
                "parents": list(parents),
                "policy": policy,
                "revision": revision,
                "available": True,
                "event": None,
            }
            if node_id in nodes:
                old = nodes[node_id]
                if any(old[key] != node[key] for key in ("kind", "reference", "parents", "policy", "revision")):
                    raise SourceLifecycleError("Conflicting node binding")  # noqa: TRY003
                await self._propagate(nodes)
                return
            try:
                if kind == "source":
                    await self.runtime.records.for_scope(self.scope_id).get_source(
                        reference.source_type, reference.source_id
                    )
                elif kind == "memory":
                    await self.runtime.memory.for_scope(self.scope_id).get(GetMemoryEntryRequest(citation=reference))
                else:
                    await self.runtime.records.for_scope(self.scope_id).get_artifact_revision(
                        reference.family, reference.artifact_id, reference.revision
                    )
            except Exception as error:
                raise SourceLifecycleError("Registration reference cannot be read") from error  # noqa: TRY003
            nodes[node_id] = node
            self._states(nodes)
            await self._save({node_id: node}, new=node_id)
            await self._propagate(nodes)

    async def apply(self, event):
        if not isinstance(event, SourceLifecycleEvent):
            raise SourceLifecycleError("Expected a lifecycle event")  # noqa: TRY003
        async with self.runtime._scope_operation(self.scope_id), self.runtime._locked(self.scope_id):
            nodes = await self._load()
            node = nodes.get(event.node_id)
            if node is None or node["kind"] != "source" or event.revision != node["revision"]:
                raise SourceLifecycleError("Unknown Source or revision")  # noqa: TRY003
            previous = node["event"]
            value = event.model_dump(mode="json")
            if previous is not None and (
                event.sequence < previous["sequence"] or (event.sequence == previous["sequence"] and value != previous)
            ):
                raise SourceLifecycleError("Event sequence conflict")  # noqa: TRY003
            node["event"] = value
            node["available"] = event.available
            self._states(nodes)
            # Persist intent first. On interruption replay reconciles actual native state.
            await self._save(nodes)
            await self._propagate(nodes)
            return sorted(identity for identity, value in nodes.items() if value["available"])

    async def _propagate(self, nodes):
        memories = [node for node in nodes.values() if node["kind"] == "memory"]
        if not memories:
            return
        async with self.runtime._context(self.scope_id) as context:
            service = context.artifacts.memory
            current = await service.head(context.artifacts.memory_artifact_id)
            versions = {entry.entry_id: entry for entry in await service.entries(current)}
            states = {entry.entry_id: entry.state for entry in current.content.manifest.entries}
            inactive, active = [], []
            for node in memories:
                reference = self._reference(node)
                entry = versions.get(reference.entry_id)
                if entry is None or entry.entry_version_id != reference.entry_version_id:
                    raise SourceLifecycleError("Registered Memory version changed")  # noqa: TRY003
                desired = "active" if node["available"] else "inactive"
                if states[entry.entry_id] != desired:
                    (active if node["available"] else inactive).append(entry)
            if inactive:
                current = await service.forget(current, entries=inactive, reason="Source evidence unavailable")
            if active:
                await service.reactivate(current, entries=active, reason="Source evidence restored")

    async def resolve(self, node_id, *, purpose):
        nodes = await self._load()
        if purpose not in ("generation", "audit") or node_id not in nodes:
            raise SourceLifecycleError("Unknown node or purpose")  # noqa: TRY003
        node = nodes[node_id]
        if purpose == "generation" and not node["available"]:
            raise SourceLifecycleError("Evidence is unavailable for generation")  # noqa: TRY003
        return self._reference(node)
