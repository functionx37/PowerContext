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

"""Full physical-page PDF capture and offline cited page retrieval."""

import hashlib
import io
import json
import math
import re
from collections import Counter

from pydantic import BaseModel, Field

from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TextEvidence


class PDFDocumentInput(BaseModel):
    document_id: str = Field(min_length=1)
    content: bytes


class PDFPageInput(BaseModel):
    document_id: str
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_number: int = Field(ge=1, strict=True)
    text: str


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    if not value.document_id.strip() or not value.content:
        raise ValueError("Empty document identity or PDF")  # noqa: TRY003
    try:
        pages = _extract_pages(value)
    except Exception as error:
        raise ValueError("Unable to completely parse PDF") from error  # noqa: TRY003
    return pages


def _extract_pages(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(value.content))
    if reader.is_encrypted and not reader.decrypt(""):
        raise ValueError("PDF requires a password")  # noqa: TRY003
    digest = hashlib.sha256(value.content).hexdigest()
    pages = tuple(
        PDFPageInput(
            document_id=value.document_id, document_sha256=digest, page_number=number, text=page.extract_text() or ""
        )
        for number, page in enumerate(reader.pages, 1)
    )
    if not pages:
        raise ValueError("PDF has no pages")  # noqa: TRY003
    return pages


class PDFPageSource(Source):
    page: PDFPageInput


class _PDFProjection:
    name = "powercontext.text-evidence"
    version = "1"
    source_class = PDFPageSource
    output_class = TextEvidence

    def project(self, source):
        page = source.page
        return TextEvidence(
            source_type="pdf-page",
            source_id=source.name,
            content=f"{page.document_id}\n{page.text}",
            metadata={
                "document_id": page.document_id,
                "document_sha256": page.document_sha256,
                "page_number": page.page_number,
            },
        )


class _PDFDefinition:
    name = "pdf-page"
    version = "1"
    input_class = PDFPageInput
    source_class = PDFPageSource
    projections = (_PDFProjection(),)

    async def resolve(self, value):
        identity = json.dumps([value.document_id, value.document_sha256, value.page_number], ensure_ascii=False)
        digest = hashlib.sha256(identity.encode()).hexdigest()
        return PDFPageSource(name=f"pdf:{digest}", materialization=SourceMaterialization.CAPTURED, page=value)

    async def read(self, source):
        return source.page


PDF_PAGE_SOURCE_DEFINITION = _PDFDefinition()


async def search_pdf_pages(memory, question: str, limit: int = 10):
    if type(limit) is not int or limit <= 0:
        raise ValueError("limit must be a positive integer")  # noqa: TRY003
    # Page collections are bounded documents; a single public list read supplies corpus
    # statistics and exact current citations without manufacturing reference identities.
    page = await memory.list()
    records = [record for record in page.entries if any(s.source_type == "pdf-page" for s in record.entry.sources)]
    if not records:
        return ()
    stop = frozenset([
        "a",
        "an",
        "the",
        "of",
        "to",
        "in",
        "for",
        "on",
        "by",
        "and",
        "or",
        "is",
        "was",
        "were",
        "what",
        "how",
        "did",
        "does",
        "do",
        "from",
        "as",
        "at",
        "with",
        "its",
        "it",
    ])

    def tokens(text):
        return [t for t in re.findall(r"[a-z]+|\d+", text.lower()) if t not in stop]

    query = Counter(tokens(question))
    documents = [Counter(tokens(record.entry.text)) for record in records]
    frequencies = Counter(term for document in documents for term in document)
    average = sum(sum(document.values()) for document in documents) / len(documents) or 1
    scores = []
    for index, document in enumerate(documents):
        length = sum(document.values())
        score = sum(
            count
            * math.log(1 + (len(documents) - frequencies[term] + 0.5) / (frequencies[term] + 0.5))
            * document[term]
            * 2.5
            / (document[term] + 1.5 * (0.25 + 0.75 * length / average))
            for term, count in query.items()
            if document[term]
        )
        scores.append((score, index))
    selected, identities = [], set()
    for _, index in sorted(scores, key=lambda pair: (-pair[0], pair[1])):
        record = records[index]
        identity = tuple((s.source_type, s.source_id) for s in record.entry.sources)
        if identity not in identities:
            selected.append(record.citation)
            identities.add(identity)
        if len(selected) == limit:
            break
    return tuple(selected)
