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
from dataclasses import dataclass
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
    words = re.findall(r"[a-z]+|\d+|[^\W\da-z_]+", text.lower())
    result = []
    for word in words:
        if re.search(r"[\u3400-\u9fff]", word):
            result.extend(word)
            result.extend(left + right for left, right in pairwise(word))
            continue
        if word in _STOP:
            continue
        if word.endswith("ies"):
            word = word[:-3] + "y"
        elif len(word) > 4 and word.endswith("s") and not word.endswith(("ss", "us")):
            word = word[:-1]
        for root in (
            "activat",
            "inhibit",
            "express",
            "differenti",
            "prolifer",
            "associat",
            "induc",
            "reduc",
            "increas",
            "decreas",
            "mutat",
            "regulat",
            "infect",
            "treat",
            "develop",
            "signal",
            "surviv",
            "bind",
        ):
            if word.startswith(root):
                word = root
                break
        result.append(word)
    return result


def _sentence_spans(text):
    # Keep abbreviations, decimals, and punctuation inside the original sentence.
    boundaries = [0]
    for match in re.finditer(r"[.!?][\"'\u2019\u201d\)\]]*\s+|[\u3002\uff01\uff1f]\s*|\n+", text):
        prefix = text[: match.start() + 1]
        if "\n" not in match.group() and re.search(
            r"(?:\b(?:e\.g|i\.e|et al|vs|Fig|Dr|Mr|Mrs|Prof)|\b[A-Z])\.$",
            prefix,
            re.IGNORECASE,
        ):
            continue
        boundaries.append(match.end())
    boundaries.append(len(text))
    for start, end in pairwise(boundaries):
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start < end:
            yield start, end


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


@dataclass(frozen=True)
class _Sentence:
    fragment: PreparedEvidenceFragment
    words: frozenset[str]
    score: float


@dataclass(frozen=True)
class _Selection:
    indices: tuple[int, ...]
    fragments: tuple[PreparedEvidenceFragment, ...]
    words: frozenset[str]
    score: float
    cost: int


def _sentences(request, candidates):
    entries, seen = [], set()
    for group in candidates:
        for hit in group.hits:
            address = MemoryEntryAddress(
                memory=ArtifactAddress(scope_id=group.scope_id, artifact=hit.memory_ref),
                entry_id=hit.entry_id,
                entry_version_id=hit.entry_version_id,
            )
            if _identity(address) not in seen:
                seen.add(_identity(address))
                entries.append((address, hit.text))
    query_words = _tokens(request.query)
    query = dict.fromkeys(query_words)
    frequencies = Counter(word for _, text in entries for word in set(_tokens(text)))
    weights = {word: math.log1p((len(entries) + 0.5) / (frequencies[word] + 0.5)) for word in query}
    total = sum(weights.values()) or 1
    bigrams = set(pairwise(query_words))
    sentences, texts = [], {_identity(address): text for address, text in entries}
    for address, text in entries:
        spans = list(_sentence_spans(text))
        words = [_tokens(text[start:end]) for start, end in spans]
        coverages = [sum(weights.get(word, 0) for word in sorted(set(value))) / total for value in words]
        document_weight = 0.5 + 0.5 * max(coverages, default=0)
        seen_text = set()
        for index, ((start, end), value, coverage) in enumerate(zip(spans, words, coverages, strict=True)):
            literal = text[start:end]
            if literal in seen_text:
                continue
            seen_text.add(literal)
            # Neighbouring result sentences can carry numbers or anaphora without
            # repeating the claim's entities. Retain them as lower-weight evidence.
            neighbour = max(coverages[max(0, index - 1) : index + 2], default=0)
            if not coverage and (
                neighbour < 0.5
                or not re.search(
                    r"\b(this|these|thus|therefore|result|conclu|suggest|demonstrat)|\d", literal, re.IGNORECASE
                )
            ):
                continue
            phrase = len(bigrams.intersection(pairwise(value))) / (len(bigrams) or 1)
            result = bool(
                re.search(
                    r"\b(result|conclu|found|findings|show|demonstrat|observ|reveal|suggest|confirm|significant)",
                    literal,
                    re.IGNORECASE,
                )
            )
            score = document_weight * (coverage**1.6 + 0.25 * phrase) * (1.2 if result else 1)
            if not coverage:
                score = document_weight * neighbour * 0.12
            sentences.append(_Sentence(PreparedEvidenceFragment(address, start, end, literal), frozenset(value), score))
    return sentences, texts, weights


def _merge(fragments, fragment, texts):
    fragments = sorted((*fragments, fragment), key=lambda f: (_identity(f.address), f.start, f.end))
    merged = []
    for current in fragments:
        if merged and merged[-1].address == current.address:
            previous = merged[-1]
            text = texts[_identity(current.address)]
            if previous.end >= current.start or not text[previous.end : current.start].strip():
                end = max(previous.end, current.end)
                merged[-1] = PreparedEvidenceFragment(current.address, previous.start, end, text[previous.start : end])
                continue
        merged.append(current)
    return tuple(merged)


def _prune(selections, width=64):
    # Preserve different partial selections: even a currently dominated state can
    # become best when an adjacent sentence shares its citation. Reserve space for
    # cheap states as well, so later evidence can replace an expensive early choice.
    if len(selections) <= width:
        return selections
    by_score = sorted(selections, key=lambda state: (-state.score, state.cost))[: width * 3 // 4]
    chosen = {state.indices for state in by_score}
    for state in sorted(selections, key=lambda state: (state.cost, -state.score)):
        if state.indices not in chosen:
            by_score.append(state)
            chosen.add(state.indices)
        if len(by_score) == width:
            break
    return by_score


def select_evidence(request, candidates):
    sentences, texts, weights = _sentences(request, candidates)
    total = sum(weights.values()) or 1
    empty = _Selection((), (), frozenset(), 0, 0)
    states = [empty]
    # Process in source order: adjacent sentences can then share a citation as
    # soon as they are considered. Bound work for long recalled documents.
    ranked = sorted(range(len(sentences)), key=lambda i: (-sentences[i].score, i))[:96]
    for index in sorted(ranked):
        sentence = sentences[index]
        proposals = list(states)
        for state in states:
            fragments = _merge(state.fragments, sentence.fragment, texts)
            cost = len(_render(fragments).encode("utf-8"))
            if cost > request.max_bytes:
                continue
            # Discount repetition without dropping a distinct quantitative result
            # or a refutation that differs in only a few words.
            redundancy = max(
                (
                    len(sentence.words & sentences[i].words) / (len(sentence.words | sentences[i].words) or 1)
                    for i in state.indices
                ),
                default=0,
            )
            words = state.words | sentence.words
            new_coverage = sum(weights.get(word, 0) for word in sorted(words - state.words)) / total
            score = state.score + sentence.score * (1 - 0.5 * redundancy) + 0.6 * new_coverage
            proposals.append(_Selection((*state.indices, index), fragments, words, score, cost))
        states = _prune(proposals)
    best = max(states, key=lambda state: (state.score, -state.cost))
    if not best.fragments:
        return PreparedContextBuild(context=PreparedContext(status="empty", content=None, content_bytes=0), origins=())
    content = _render(best.fragments)
    return PreparedContextBuild(
        context=PreparedContext(status="ready", content=content, content_bytes=len(content.encode("utf-8"))),
        origins=tuple(f.address for f in best.fragments),
        fragments=best.fragments,
    )
