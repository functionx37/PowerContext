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

"""Canonical, independently verifiable context packs and prefix deltas."""

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass

_PACK = "powercontext.context-pack.v1"
_DELTA = "powercontext.context-pack-delta.v1"


class ContextPackError(ValueError):
    """Invalid context pack protocol value."""


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _items(value):
    if not isinstance(value, tuple) or any(type(item) is not bytes for item in value):
        raise ContextPackError("Chunks must be a tuple of bytes")  # noqa: TRY003
    try:
        for item in value:
            item.decode("utf-8")
    except UnicodeError as error:
        raise ContextPackError("Chunks must be valid UTF-8") from error  # noqa: TRY003
    return value


def _encoded(items):
    return [base64.b64encode(item).decode("ascii") for item in items]


def _decoded(items):
    if not isinstance(items, list) or any(type(item) is not str for item in items):
        raise ContextPackError("Expected a Base64 string array")  # noqa: TRY003
    try:
        result = tuple(base64.b64decode(item, validate=True) for item in items)
        if _encoded(result) != items:
            raise ContextPackError("Noncanonical Base64")  # noqa: TRY003
        return _items(result)
    except (ValueError, binascii.Error) as error:
        raise ContextPackError("Invalid Base64 chunks") from error  # noqa: TRY003


def _digest(value):
    if type(value) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ContextPackError("Invalid digest")  # noqa: TRY003


def _payload(data, fields, schema):
    try:

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ContextPackError("Duplicate wire field")  # noqa: TRY003
                result[key] = value
            return result

        value = json.loads(data.decode("utf-8"), object_pairs_hook=unique)
    except (ValueError, UnicodeError, AttributeError) as error:
        raise ContextPackError("Invalid wire JSON") from error  # noqa: TRY003
    if not isinstance(value, dict) or set(value) != fields or value["schema"] != schema:
        raise ContextPackError("Invalid wire fields or schema")  # noqa: TRY003
    return value


@dataclass(frozen=True)
class ContextPack:
    items: tuple[bytes, ...]
    digest: str
    byte_count: int

    @classmethod
    def build(cls, items):
        _items(items)
        unsigned = {"schema": _PACK, "items": _encoded(items)}
        digest = "sha256:" + hashlib.sha256(_json(unsigned)).hexdigest()
        count = 0
        while True:
            actual = len(_json({**unsigned, "digest": digest, "byte_count": count}))
            if actual == count:
                return cls(items, digest, count)
            count = actual

    @classmethod
    def from_content(cls, content, *, chunk_bytes=512):
        if type(chunk_bytes) is not int or chunk_bytes <= 0:
            raise ContextPackError("Chunk limit must be a positive integer")  # noqa: TRY003
        if content is None:
            content = ""
        if not isinstance(content, str):
            raise ContextPackError("Content must be text")  # noqa: TRY003
        chunks, current, size = [], [], 0
        for char in content:
            try:
                encoded = char.encode("utf-8")
            except UnicodeError as error:
                raise ContextPackError("Content must be valid UTF-8") from error  # noqa: TRY003
            if len(encoded) > chunk_bytes:
                raise ContextPackError("Chunk limit splits a UTF-8 character")  # noqa: TRY003
            if size + len(encoded) > chunk_bytes:
                chunks.append(b"".join(current))
                current, size = [], 0
            current.append(encoded)
            size += len(encoded)
            # Line boundaries keep stable prefixes useful when a later item changes.
            if char == "\n":
                chunks.append(b"".join(current))
                current, size = [], 0
        if current:
            chunks.append(b"".join(current))
        return cls.build(tuple(chunks))

    def to_bytes(self):
        return _json({
            "schema": _PACK,
            "items": _encoded(self.items),
            "digest": self.digest,
            "byte_count": self.byte_count,
        })

    @classmethod
    def from_bytes(cls, data):
        value = _payload(data, {"schema", "items", "digest", "byte_count"}, _PACK)
        pack = cls.build(_decoded(value["items"]))
        if (
            type(value["byte_count"]) is not int
            or value["byte_count"] != pack.byte_count
            or value["digest"] != pack.digest
        ):
            raise ContextPackError("Pack digest or byte count mismatch")  # noqa: TRY003
        return pack


@dataclass(frozen=True)
class ContextPackDelta:
    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    def __post_init__(self):
        _digest(self.base_digest)
        _digest(self.target_digest)
        if type(self.prefix_items) is not int or self.prefix_items < 0:
            raise ContextPackError("Invalid prefix")  # noqa: TRY003
        _items(self.appended)

    @classmethod
    def between(cls, base, target):
        base = ContextPack.from_bytes(base.to_bytes())
        target = ContextPack.from_bytes(target.to_bytes())
        prefix = 0
        for first, second in zip(base.items, target.items, strict=False):
            if first != second:
                break
            prefix += 1
        return cls(base.digest, target.digest, prefix, target.items[prefix:])

    def to_bytes(self):
        return _json({
            "schema": _DELTA,
            "base_digest": self.base_digest,
            "target_digest": self.target_digest,
            "prefix_items": self.prefix_items,
            "appended": _encoded(self.appended),
        })

    @property
    def byte_count(self):
        return len(self.to_bytes())

    @classmethod
    def from_bytes(cls, data):
        value = _payload(data, {"schema", "base_digest", "target_digest", "prefix_items", "appended"}, _DELTA)
        return cls(value["base_digest"], value["target_digest"], value["prefix_items"], _decoded(value["appended"]))


def apply_context_pack_delta(base, delta):
    base = ContextPack.from_bytes(base.to_bytes())
    if delta.base_digest != base.digest or delta.prefix_items > len(base.items):
        raise ContextPackError("Wrong base or prefix outside base")  # noqa: TRY003
    target = ContextPack.build(base.items[: delta.prefix_items] + delta.appended)
    if target.digest != delta.target_digest:
        raise ContextPackError("Target digest mismatch")  # noqa: TRY003
    return target
