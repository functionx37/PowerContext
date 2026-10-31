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

"""Query-weighted extraction of exact sentence spans under the full wire budget."""

import json
import math
import re
from collections import Counter
from itertools import pairwise

from powercontext.artifacts import ArtifactAddress
from powercontext.builtin.runtime.models import PreparedContext
from powercontext.builtin.runtime.prepared_context import (
    MemoryEntryAddress,
    PreparedContextBuild,
    PreparedEvidenceFragment,
)
from powercontext.builtin.runtime.prepared_text import TRUST_POLICY

_STOP = frozenset([
    "a",
    "an",
    "the",
    "and",
    "or",
    "of",
    "to",
    "in",
    "on",
    "for",
    "by",
    "with",
    "at",
    "as",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "that",
    "this",
    "these",
    "those",
    "it",
    "its",
    "from",
    "can",
    "may",
    "has",
    "have",
    "had",
    "not",
    "no",
    "do",
    "does",
    "did",
    "than",
    "which",
    "when",
    "how",
    "what",
    "who",
    "into",
    "through",
    "during",
])


def _tokens(text):
    words = re.findall(r"[a-z]+|\d+", text.lower())
    return [word[:-1] if len(word) > 4 and word.endswith("s") else word for word in words if word not in _STOP]


def _render(fragments):
    items = [
        {
            "citation": {
                "scope_id": f.address.memory.scope_id,
                "memory_ref": f.address.memory.artifact.model_dump(mode="json"),
                "entry_id": f.address.entry_id,
                "entry_version_id": f.address.entry_version_id,
            },
            "content": f.text,
            "start": f.start,
            "end": f.end,
        }
        for f in fragments
    ]
    return (
        TRUST_POLICY
        + "\nBEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1\n"
        + json.dumps({"trust": "untrusted_history", "items": items}, ensure_ascii=False, separators=(",", ":"))
        + "\nEND_POWERCONTEXT_PREPARED_CONTEXT_V1"
    )


def _identity(address):
    return (
        address.memory.scope_id,
        address.memory.artifact.artifact_id,
        address.memory.artifact.revision,
        address.entry_id,
        address.entry_version_id,
    )


def select_evidence(request, candidates):  # noqa: C901 - extract, rank and budget one candidate set
    sentences, texts = [], {}
    seen = set()
    for group in candidates:
        for hit in group.hits:
            address = MemoryEntryAddress(
                memory=ArtifactAddress(scope_id=group.scope_id, artifact=hit.memory_ref),
                entry_id=hit.entry_id,
                entry_version_id=hit.entry_version_id,
            )
            if _identity(address) in seen:
                continue
            seen.add(_identity(address))
            texts[_identity(address)] = hit.text
            # Splitting only at whitespace after punctuation preserves decimal numbers
            # and every original character inside each sentence.
            boundaries = [0, *(m.end() for m in re.finditer(r"(?<=[.!?])\s+|\n+", hit.text)), len(hit.text)]
            for start, end in pairwise(boundaries):
                while start < end and hit.text[start].isspace():
                    start += 1
                while end > start and hit.text[end - 1].isspace():
                    end -= 1
                if start < end:
                    sentences.append((address, start, end, Counter(_tokens(hit.text[start:end]))))
    query = Counter(_tokens(request.query))
    frequencies = Counter(term for _, _, _, words in sentences for term in words)
    ranked = []
    for index, (address, start, end, words) in enumerate(sentences):
        score = sum(
            math.log(1 + (len(sentences) + 0.5) / (frequencies[term] + 0.5)) * min(count, words[term])
            for term, count in query.items()
            if words[term]
        )
        score /= math.sqrt(100 + len(texts[_identity(address)][start:end].encode("utf-8")))
        ranked.append((score, index))
    selected = []
    for score, index in sorted(ranked, key=lambda pair: (-pair[0], pair[1])):
        if score <= 0:
            continue
        address, start, end, _ = sentences[index]
        proposed = list(selected)
        # Coalesce adjacent evidence to avoid paying citation overhead repeatedly.
        merged = []
        for fragment in proposed:
            if fragment.address == address and (
                texts[_identity(address)][min(end, fragment.end) : max(start, fragment.start)].strip() == ""
            ):
                start, end = min(start, fragment.start), max(end, fragment.end)
            else:
                merged.append(fragment)
        merged.append(PreparedEvidenceFragment(address, start, end, texts[_identity(address)][start:end]))
        content = _render(merged)
        if len(content.encode("utf-8")) <= request.max_bytes:
            selected = merged
    if not selected:
        return PreparedContextBuild(context=PreparedContext(status="empty", content=None, content_bytes=0), origins=())
    content = _render(selected)
    return PreparedContextBuild(
        context=PreparedContext(status="ready", content=content, content_bytes=len(content.encode("utf-8"))),
        origins=tuple(f.address for f in selected),
        fragments=tuple(selected),
    )
