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

"""Event-loop-local embedding batching, shared in-flight work and bounded LRU."""

import asyncio
import math
from collections import OrderedDict

from powercontext.builtin.inference.models import EmbeddingResult, InferenceUsage


class CoalescingEmbeddingModel:
    def __init__(self, model, *, max_batch_size=64, coalesce_ms=5.0, cache_size=1024):
        if type(max_batch_size) is not int or max_batch_size <= 0:
            raise ValueError("max_batch_size must be positive")  # noqa: TRY003
        if type(cache_size) is not int or cache_size < 0:
            raise ValueError("cache_size must be nonnegative")  # noqa: TRY003
        if type(coalesce_ms) not in (int, float) or not math.isfinite(coalesce_ms) or coalesce_ms < 0:
            raise ValueError("coalesce_ms must be finite and nonnegative")  # noqa: TRY003
        self.profile = model.profile
        self._model = model
        self._max_batch_size = max_batch_size
        self._delay = coalesce_ms / 1000
        self._cache_size = cache_size
        self._cache = OrderedDict()
        self._pending = {}
        self._queued = []
        self._timer = None
        self._tasks = set()

    async def embed(self, texts):
        loop = asyncio.get_running_loop()
        waiting = {}
        vectors = {}
        for text in texts:
            if text in vectors or text in waiting:
                continue
            if text in self._cache:
                vectors[text] = self._cache[text]
                self._cache.move_to_end(text)
            else:
                if text not in self._pending:
                    future = loop.create_future()
                    # Retrieving the exception also covers an abandoned/cancelled waiter.
                    future.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
                    self._pending[text] = future
                    self._queued.append(text)
                waiting[text] = self._pending[text]
        if self._queued and self._timer is None:
            self._timer = loop.call_later(self._delay, self._dispatch)
        usages = {}
        for text, future in waiting.items():
            vector, batch, usage = await asyncio.shield(future)
            vectors[text] = vector
            usages[batch] = usage

        def total(field):
            values = [getattr(u, field) for u in usages.values() if getattr(u, field) is not None]
            return sum(values) if values else None

        return EmbeddingResult(
            vectors=tuple(vectors[text] for text in texts),
            usage=InferenceUsage(
                requests=sum(u.requests for u in usages.values()),
                input_tokens=total("input_tokens"),
                output_tokens=total("output_tokens"),
            ),
        )

    def _dispatch(self):
        self._timer = None
        queued, self._queued = self._queued, []
        for offset in range(0, len(queued), self._max_batch_size):
            texts = tuple(queued[offset : offset + self._max_batch_size])
            task = asyncio.create_task(self._run(texts))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _run(self, texts):
        batch = object()
        try:
            result = await self._embed_batch(texts)
        except (Exception, asyncio.CancelledError) as error:
            for text in texts:
                self._pending.pop(text).set_exception(error)
        else:
            for text, vector in zip(texts, result.vectors, strict=True):
                if self._cache_size:
                    self._cache[text] = vector
                    self._cache.move_to_end(text)
                    while len(self._cache) > self._cache_size:
                        self._cache.popitem(last=False)
                self._pending.pop(text).set_result((vector, batch, result.usage))

    async def _embed_batch(self, texts):
        result = await self._model.embed(texts)
        if len(result.vectors) != len(texts):
            raise ValueError("Embedding vector count mismatch")  # noqa: TRY003
        return result
