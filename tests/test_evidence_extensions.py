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

"""Cross-component regressions for captured evidence and lifecycle recovery."""

import json
import sqlite3

import pytest
from sqlalchemy.exc import IntegrityError

from powercontext.artifacts import ArtifactAddress, ArtifactRef
from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    CaptureSource,
    GetMemoryEntryRequest,
    PrepareContextRequest,
    RememberMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.context_pack import ContextPack, ContextPackDelta, ContextPackError
from powercontext.builtin.runtime.prepared_context import (
    MemoryEntryAddress,
    PreparedContextBuilder,
    PreparedMemoryCandidates,
)
from powercontext.builtin.runtime.source_lifecycle import SourceLifecycleEvent
from powercontext.builtin.scope import ScopeDraft


def test_extracted_spans_preserve_decimal_evidence_and_cross_scope_identity():
    reference = ArtifactRef(family="memory", artifact_id="shared", revision=1)
    candidates = tuple(
        PreparedMemoryCandidates(
            scope_id=scope,
            memory_ref=reference,
            hits=(
                MemoryHit(
                    memory_ref=reference,
                    entry_id="same-entry",
                    entry_version_id="same-version",
                    text=text,
                    score=1,
                    matched_by=("fts",),
                ),
            ),
        )
        for scope, text in (
            ("left", "Sensor threshold is 37.5 degrees."),
            ("right", "Sensor threshold is 19.2 degrees."),
        )
    )
    build = PreparedContextBuilder().build_scopes_result(
        request=PrepareContextRequest(query="sensor threshold degrees", max_bytes=2400, evidence_selection=True),
        current_scope_id="left",
        memory_candidates=candidates,
    )
    assert {fragment.text for fragment in build.fragments} == {
        "Sensor threshold is 37.5 degrees.",
        "Sensor threshold is 19.2 degrees.",
    }
    assert {fragment.address.memory.scope_id for fragment in build.fragments} == {"left", "right"}
    for fragment, origin in zip(build.fragments, build.origins, strict=True):
        assert isinstance(origin, MemoryEntryAddress)
        assert origin == fragment.address
        assert origin.memory == ArtifactAddress(scope_id=origin.memory.scope_id, artifact=reference)


@pytest.mark.parametrize(
    "change",
    [
        {"items": ["!!!!"]},
        {"items": ["/w=="]},
        {"extra": True},
        {"byte_count": True},
    ],
)
def test_pack_decoder_rejects_invalid_wire_values(change):
    payload = json.loads(ContextPack.build((b"evidence",)).to_bytes())
    with pytest.raises(ContextPackError):
        ContextPack.from_bytes(json.dumps({**payload, **change}).encode())


def test_delta_decoder_rejects_duplicate_wire_keys():
    pack = ContextPack.build((b"evidence",))
    data = ContextPackDelta.between(pack, pack).to_bytes()
    duplicate = data[:-1] + b',"prefix_items":0}'
    with pytest.raises(ContextPackError):
        ContextPackDelta.from_bytes(duplicate)


def test_context_pack_rejects_invalid_unicode_text():
    with pytest.raises(ContextPackError):
        ContextPack.from_content("\ud800")


@pytest.mark.asyncio
async def test_lifecycle_replays_interrupted_native_write_after_restart(tmp_path):
    database = tmp_path / "recovery.db"
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{database}"))
    event = SourceLifecycleEvent(node_id="source", revision=1, sequence=1, available=False, reason="withdrawn")
    async with open_builtin_runtime(config) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(
            ScopeDraft(title="Recovery", summary="Evidence", idempotency_key="recovery")
        )
        service = runtime.lifecycle.for_scope(scope.scope_id)
        source = await runtime.sources.for_scope(scope.scope_id).capture(
            CaptureSource(source_id="original", content="Original evidence", metadata={})
        )
        await service.register_source("source", source.source_ref, revision=1)
        result = await runtime.memory.for_scope(scope.scope_id).remember(
            RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text="Original evidence"),))
        )
        assert result.entry is not None
        citation = result.entry.citation
        await service.register_memory("fact", citation, parents=("source",), policy="all")
        with sqlite3.connect(database) as connection:
            connection.execute(
                "CREATE TRIGGER interrupt_lifecycle BEFORE INSERT ON pc_artifacts "
                "WHEN NEW.family = 'memory' BEGIN SELECT RAISE(ABORT, 'interrupted'); END"
            )
        with pytest.raises(IntegrityError):
            await service.apply(event)
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TRIGGER interrupt_lifecycle")
    async with open_builtin_runtime(config) as runtime:
        service = runtime.lifecycle.for_scope(scope.scope_id)
        assert await service.apply(event) == []
        memory = runtime.memory.for_scope(scope.scope_id)
        assert not (await memory.list()).entries
        head = (await memory.list(include_inactive=True)).memory_ref
        await service.apply(event)
        assert (await memory.list(include_inactive=True)).memory_ref == head
        assert await service.resolve("fact", purpose="audit") == citation
        assert (await memory.get(GetMemoryEntryRequest(citation=citation))).entry.text == "Original evidence"
