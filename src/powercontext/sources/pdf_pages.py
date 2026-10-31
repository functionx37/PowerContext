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

from powercontext.sources.definitions import SourceDefinition, SourceProjection
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
    source_class: type[PDFPageSource] = PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PDFPageSource) -> TextEvidence:
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
    input_class: type[PDFPageInput] = PDFPageInput
    source_class: type[PDFPageSource] = PDFPageSource
    projections: tuple[SourceProjection[PDFPageSource], ...] = (_PDFProjection(),)

    async def resolve(self, value: PDFPageInput) -> PDFPageSource:
        identity = json.dumps([value.document_id, value.document_sha256, value.page_number], ensure_ascii=False)
        digest = hashlib.sha256(identity.encode()).hexdigest()
        return PDFPageSource(name=f"pdf:{digest}", materialization=SourceMaterialization.CAPTURED, page=value)

    async def read(self, source: PDFPageSource) -> PDFPageInput:
        return source.page


PDF_PAGE_SOURCE_DEFINITION: SourceDefinition[PDFPageInput, PDFPageSource, PDFPageInput] = _PDFDefinition()


async def search_pdf_pages(memory, question: str, limit: int = 10):
    if type(limit) is not int or limit <= 0:
        raise ValueError("limit must be a positive integer")  # noqa: TRY003
    # Read current records through Memory so ranking never creates citation identities.
    page = await memory.list()
    records = [record for record in page.entries if any(s.source_type == "pdf-page" for s in record.entry.sources)]
    if not records:
        return ()
    scores = _rank_pages([record.entry.text for record in records], question)
    selected, identities = [], set()
    for _, index in sorted(scores, key=lambda pair: (-pair[0], pair[1])):
        record = records[index]
        identity = frozenset(s.source_id for s in record.entry.sources if s.source_type == "pdf-page")
        if identity not in identities:
            selected.append(record.citation)
            identities.add(identity)
        if len(selected) == limit:
            break
    return tuple(selected)


_STOP = frozenset([
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
    "are",
    "was",
    "were",
    "be",
    "been",
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
    "has",
    "have",
    "had",
    "any",
    "that",
    "this",
    "these",
    "those",
    "which",
    "who",
    "can",
    "only",
    "use",
    "using",
    "used",
    "give",
    "answer",
    "respond",
    "response",
    "question",
    "assuming",
    "perspective",
    "analyst",
    "details",
    "shown",
    "within",
    "relying",
    "define",
    "calculate",
    "reported",
    "directly",
    "explicitly",
    "outlined",
    "state",
    "quantity",
    "primarily",
    "important",
    "ongoing",
    "materially",
    "usd",
    "million",
    "millions",
    "fy",
])

# Financial terminology, rather than document/question-specific answers. Expansion is
# weighted below literal terms and is used for both headings and ordinary page text.
_CONCEPTS = (
    (r"\b(geograph\w*|countr\w*|region\w*)\b", "geography region country international global segment business"),
    (r"\b(legal|litigat\w*|lawsuit\w*|battles?|proceedings?)\b", "legal litigation lawsuit proceeding contingency"),
    (
        r"\b(income statements?|statements? of (income|operations|earnings)|p\s*&\s*l)\b",
        "income statement revenue expense profit operation",
    ),
    (r"\b(cash flows?|capex|capital expend\w*)\b", "cash flow activity capital expenditure spending"),
    (r"\bebitda\b|\bd\s*&\s*a\b", "operating income profit depreciation amortization"),
    (r"\b(balance sheets?|financial position)\b", "balance sheet asset liability equity"),
    (r"\b(revenues?|net sales)\b", "revenue sale"),
)


def _terms(text):
    text = re.sub(r"\bfy\s*(\d{4})\b", r"\1", text.lower())
    words = re.findall(r"[a-z]+|\d+", text)
    result = []
    for word in words:
        if word in _STOP:
            continue
        if word.endswith("ies"):
            word = word[:-3] + "y"
        elif len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us")):
            word = word[:-1]
        for root in ("operat", "restructur", "geograph", "litigat", "amortiz", "depreciat"):
            if word.startswith(root):
                word = root
                break
        result.append(word)
    return result


def _rank_pages(texts, question):
    identities, bodies = zip(*(text.partition("\n")[::2] for text in texts), strict=True)
    # The projection's first line identifies the report. Do not let a different
    # company's report win solely because it repeats the same financial vocabulary.
    compact_query = re.sub(r"[^a-z0-9]", "", question.lower())
    names = [re.split(r"[_\s](?:19|20)\d{2}", identity.lower())[0] for identity in identities]
    matches = [bool(name) and re.sub(r"[^a-z0-9]", "", name) in compact_query for name in names]
    indices = [i for i, match in enumerate(matches) if match] if any(matches) else list(range(len(texts)))
    documents = [Counter(_terms(bodies[i])) for i in indices]
    frequencies = Counter(term for document in documents for term in document)
    average = sum(document.total() for document in documents) / len(documents) or 1
    query_text = re.sub(r"\binvestment analyst\b", "", question, flags=re.IGNORECASE)
    query = dict.fromkeys(_terms(query_text), 1.0)
    for pattern, expansion in _CONCEPTS:
        if re.search(pattern, question, re.IGNORECASE):
            for term in _terms(expansion):
                query.setdefault(term, 0.45)

    def score(words, length):
        return sum(
            weight
            * math.log1p((len(documents) - frequencies[term] + 0.5) / (frequencies[term] + 0.5))
            * words[term]
            * 2.2
            / (words[term] + 1.2 * (0.65 + 0.35 * length / average))
            for term, weight in query.items()
            if words[term]
        )

    scores = []
    for index, document in zip(indices, documents, strict=True):
        body = bodies[index]
        # A page heading is stronger evidence than a passing mention in a long note.
        # Score lines separately so a table row need not resemble natural language.
        lines = [line for line in body.splitlines() if line.strip() and line.strip().lower() != "table of contents"]
        heading = Counter(_terms(" ".join(lines[:3])))
        passages = [Counter(_terms(" ".join(lines[start : start + 4]))) for start in range(0, len(lines), 3)]
        local = max((score(passage, average) for passage in passages), default=0.0)
        # Questions can require several statements, each with different vocabulary.
        # Reward each requested statement independently instead of requiring a cash
        # flow table to also mention every income-statement term (or vice versa).
        statement_bonus = _statement_score(question, lines)
        scores.append((
            score(document, document.total()) + 0.75 * score(heading, average) + 0.3 * local + statement_bonus,
            index,
        ))
    return scores


def _statement_score(question, lines):
    kinds = []
    if re.search(r"\bincome|earnings|operations|p\s*&\s*l|ebitda", question, re.IGNORECASE):
        kinds.append(r"statements? (?:of )?(?:income|operations|earnings)\b")
    if re.search(r"cash flow|capex|ebitda|d\s*&\s*a", question, re.IGNORECASE):
        kinds.append(r"statements? (?:of )?cash flows?\b")
    if re.search(r"balance sheet|financial position|asset|liabilit|equity", question, re.IGNORECASE):
        kinds.append(r"(?:balance sheets?|statements? (?:of )?financial position)\b")
    prefix = r"^(?:(?:consolidated|condensed|combined|unaudited|audited)\s+)*"
    suffix = r"(?: and comprehensive (?:income|loss))?(?:\s*\((?:continued|unaudited|loss)\))*\s*[.:]?$"
    return 12.0 * sum(
        any(re.search(prefix + kind + suffix, line, re.IGNORECASE) for line in lines[:12]) for kind in kinds
    )
