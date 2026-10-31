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

"""Evidence selection through real Memory versions and the public context builder."""

import json

import pytest

from powercontext.artifacts import MemoryCitation
from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    PrepareContextRequest,
    RememberMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.prepared_context import PreparedContextBuilder, PreparedMemoryCandidates
from powercontext.builtin.scope import ScopeDraft


async def _select(memory, query, texts, budget):
    await memory.remember(
        RememberMemoryRequest(entries=tuple(MemoryEntryInput(kind="document", text=t) for t in texts))
    )
    page = await memory.list()
    candidates = PreparedMemoryCandidates(
        scope_id=memory.scope_id,
        memory_ref=page.memory_ref,
        hits=tuple(
            MemoryHit(
                memory_ref=record.memory_ref,
                entry_id=record.entry.entry_id,
                entry_version_id=record.entry.entry_version_id,
                text=record.entry.text,
                score=1,
                matched_by=("fts",),
            )
            for record in page.entries
        ),
    )
    result = PreparedContextBuilder().build_scopes_result(
        request=PrepareContextRequest(query=query, max_bytes=budget, evidence_selection=True),
        current_scope_id=memory.scope_id,
        memory_candidates=(candidates,),
    )
    assert result.context.content_bytes == len((result.context.content or "").encode("utf-8")) <= budget
    if result.fragments:
        assert result.context.content is not None
        items = json.loads(result.context.content.splitlines()[-2])["items"]
        assert len(items) == len(result.fragments) == len(result.origins)
        for fragment, origin, item in zip(result.fragments, result.origins, items, strict=True):
            address = fragment.address
            citation = MemoryCitation(
                memory_ref=address.memory.artifact,
                entry_id=address.entry_id,
                entry_version_id=address.entry_version_id,
            )
            entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
            assert fragment.text == entry.text[fragment.start : fragment.end] == item["content"]
            assert origin == address
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize(("budget", "details"), [(1400, 5), (1800, 9)])
async def test_complete_result_can_replace_shorter_background_evidence(budget, details):
    evidence = (
        "Results showed that cobalt sensor calibration reduced threshold drift by 37.5 percent"
        + ", with blinded temperature measurements compared against a stable reference standard" * details
        + " throughout the entire follow-up period."
    )
    async with open_builtin_runtime(BuiltinConfig()) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(ScopeDraft(title="Evidence", summary="Results", idempotency_key="result"))
        result = await _select(
            runtime.memory.for_scope(scope.scope_id),
            "Cobalt sensor calibration reduces threshold drift.",
            ["Cobalt sensor calibration and threshold drift are research topics.", "Background notes. " + evidence],
            budget,
        )
    assert any(evidence in fragment.text for fragment in result.fragments)


@pytest.mark.asyncio
async def test_adjacent_follow_up_result_is_preserved_without_repeating_query_terms():
    evidence = "Results showed cobalt sensor calibration reduced drift. This effect persisted for 12 months."
    async with open_builtin_runtime(BuiltinConfig()) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(
            ScopeDraft(title="Evidence", summary="Follow-up", idempotency_key="followup")
        )
        result = await _select(
            runtime.memory.for_scope(scope.scope_id),
            "Cobalt sensor calibration reduces drift.",
            ["Administrative notes. " * 60 + evidence],
            1400,
        )
    assert any(evidence in fragment.text for fragment in result.fragments)


@pytest.mark.asyncio
async def test_unicode_only_query_matches_late_literal_evidence():
    evidence = "海洋观测温度稳定，记录值为37.5度。"  # noqa: RUF001
    async with open_builtin_runtime(BuiltinConfig()) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(ScopeDraft(title="Evidence", summary="Unicode", idempotency_key="unicode"))
        result = await _select(
            runtime.memory.for_scope(scope.scope_id),
            "海洋观测温度",
            ["行政记录。" * 80 + evidence],
            1400,
        )
    assert any(evidence in fragment.text for fragment in result.fragments)
