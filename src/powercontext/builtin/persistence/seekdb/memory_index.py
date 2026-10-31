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

"""One native statement for seekdb's independent hybrid candidate channels."""

from pyobvector import VECTOR
from sqlalchemy import bindparam, text
from typing_extensions import override

from powercontext.builtin.artifacts.memory import CapabilityNotSupportedError, MemorySearchChannels
from powercontext.builtin.artifacts.memory.canonical import validate_embedding
from powercontext.builtin.persistence.memory_index import CompositeMemoryIndex, memory_channel_hits
from powercontext.builtin.persistence.tags import memory_tag_parameters, memory_tag_sql

_FTS = """
SELECT m.memory_artifact_id, m.head_revision, m.entry_id, m.entry_version_id,
       v.text, 'fts' AS channel, MATCH(m.searchable_text) AGAINST (:query) AS relevance,
       NULL AS distance
FROM pc_memory_entry_heads AS m
JOIN pc_memory_entry_versions AS v
  ON v.scope_id = m.scope_id AND v.memory_artifact_id = m.memory_artifact_id
 AND v.entry_version_id = m.entry_version_id
WHERE m.scope_id = :scope_id AND m.memory_artifact_id IN :memory_artifact_ids
  AND MATCH(m.searchable_text) AGAINST (:query)
{tags}
ORDER BY relevance DESC, m.memory_artifact_id, m.entry_id, m.entry_version_id
LIMIT :candidate_limit
"""
_VECTOR = """
SELECT m.memory_artifact_id, m.head_revision, m.entry_id, m.entry_version_id,
       v.text, 'vector' AS channel, NULL AS relevance,
       l2_distance(m.embedding, :query_vector) AS distance
FROM pc_memory_vector_entries AS m
JOIN pc_memory_entry_versions AS v
  ON v.scope_id = m.scope_id AND v.memory_artifact_id = m.memory_artifact_id
 AND v.entry_version_id = m.entry_version_id
WHERE m.scope_id = :scope_id AND m.memory_artifact_id IN :memory_artifact_ids
{tags}
ORDER BY l2_distance(m.embedding, :query_vector) APPROXIMATE
LIMIT :candidate_limit
"""


class SeekDBMemoryIndex(CompositeMemoryIndex):
    @override
    async def search(self, connection, scope_id, request):
        if request.mode != "hybrid":
            return await super().search(connection, scope_id, request)
        profile = self.capabilities.embedding_profile
        if profile is None or request.embedding_profile != profile or request.query_vector is None:
            raise CapabilityNotSupportedError("embedding-profile")
        if not await self.vector_complete(connection, scope_id, request.memories, profile):
            raise CapabilityNotSupportedError("vector")
        tags = "" if request.tag_filter is None else memory_tag_sql("m")
        statement = text(
            "SELECT * FROM ("  # noqa: S608 - only fixed SQL templates and internal tag predicates are composed
            + _FTS.format(tags=tags)
            + ") AS lexical\nUNION ALL\nSELECT * FROM ("
            + _VECTOR.format(tags=tags)
            + ") AS semantic\n"
            "ORDER BY channel, relevance DESC, distance, memory_artifact_id, entry_id, entry_version_id"
        ).bindparams(
            bindparam("memory_artifact_ids", expanding=True), bindparam("query_vector", type_=VECTOR(profile.dimension))
        )
        if request.tag_filter is not None:
            statement = statement.bindparams(
                bindparam("tag_keys", expanding=True), bindparam("tag_hashes", expanding=True)
            )
        rows = (
            (
                await connection.execute(
                    statement,
                    {
                        "scope_id": scope_id,
                        "memory_artifact_ids": tuple(memory.artifact_id for memory in request.memories),
                        "query": request.analyzed_query,
                        "query_vector": validate_embedding(request.query_vector, dimension=profile.dimension),
                        "candidate_limit": request.candidate_limit,
                        **memory_tag_parameters(request.tag_filter),
                    },
                )
            )
            .mappings()
            .all()
        )
        return MemorySearchChannels(
            fts=memory_channel_hits((row for row in rows if row["channel"] == "fts"), request.memories),
            vector=memory_channel_hits((row for row in rows if row["channel"] == "vector"), request.memories),
        )
