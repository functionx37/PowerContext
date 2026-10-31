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

"""Financial statement recall with persisted, exact PDF page citations."""

import pytest

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    SubmitSourceObservation,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import SourceDefinitionRegistry, manifest_for_definition, project_source_for_transport
from powercontext.sources.pdf_pages import PDF_PAGE_SOURCE_DEFINITION, PDFPageInput, search_pdf_pages
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence


class _PagePipeline:
    async def extract(self, request, /):
        return tuple(
            MemoryEntryInput(
                kind="source-evidence",
                text=source.projection(TEXT_EVIDENCE_PROJECTION_KEY)["content"],
                sources=(source,),
            )
            for source in request.sources
        )


@pytest.mark.asyncio
async def test_requested_statements_survive_many_notes_and_other_reports_after_restart(tmp_path):
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'pdf.db'}"))
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    observations = []
    for document_id, texts in (
        (
            "ACME_2024_10K",
            [
                "Consolidated Statement of Income\nNet revenue 900\nOperating profit 120\nNet income 80",
                "Consolidated Statement of Cash Flows\nDepreciation and amortization 30\nCapital spending 45",
                *(
                    f"Note {i}: restructuring costs and income statements\n"
                    "Operating income, depreciation and amortization, cash flows, EBITDA and capex are discussed in management estimates."
                    for i in range(30)
                ),
            ],
        ),
        (
            "BETA_2024_10K",
            [
                f"Consolidated Statement of Income\nStatement of Cash Flows\nOperating income {i}\nDepreciation and amortization 30"
                for i in range(25)
            ],
        ),
    ):
        for number, text in enumerate(texts, 1):
            page = PDFPageInput(document_id=document_id, document_sha256="a" * 64, page_number=number, text=text)
            source = await registry.resolve(page)
            observations.append(project_source_for_transport(registry, source))
    stored = {
        source.name: TextEvidence.model_validate(source.projection(TEXT_EVIDENCE_PROJECTION_KEY))
        for source in observations
    }
    async with open_builtin_runtime(config, candidate_pipeline=_PagePipeline()) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(ScopeDraft(title="Reports", summary="Pages", idempotency_key="reports"))
        await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
        for source in observations:
            await runtime.ingestion.submit(SubmitSourceObservation(scope_id=scope.scope_id, observation=source))
        memory = runtime.memory.for_scope(scope.scope_id)
        while (await memory.flush()).processed:
            pass
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope.scope_id)
        for query in (
            "What is ACME's EBITDA less capex in FY2024 using operating income, depreciation and amortization from the income statement and cash flow statement?",
            "What restructuring costs are explicitly outlined in ACME's income statement for FY2024?",
        ):
            citations = await search_pdf_pages(memory, query, limit=20)
            locations = set()
            for citation in citations:
                record = await memory.get(GetMemoryEntryRequest(citation=citation))
                projection = stored[record.entry.sources[0].source_id]
                assert record.entry.text == projection.content.strip()
                metadata = projection.metadata
                assert metadata["document_id"] == "ACME_2024_10K"
                assert isinstance(metadata["page_number"], int)
                locations.add(metadata["page_number"])
            assert len(citations) == len(locations) == 20
            assert 1 in locations
            if "EBITDA" in query:
                assert 2 in locations
        assert len(await search_pdf_pages(memory, "ACME income statement", limit=1)) == 1
