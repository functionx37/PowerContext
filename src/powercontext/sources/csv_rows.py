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

"""Lossless, primary-key-addressed CSV row evidence."""

import csv
import io
import json
from urllib.parse import quote

from pydantic import BaseModel, model_validator

from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TextEvidence


def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    if not document_id or document_id != document_id.strip() or not primary_key_value.strip():
        raise ValueError("Invalid CSV identity")  # noqa: TRY003
    identity = f"csv:{quote(document_id, safe='')}:{quote(primary_key_value, safe='')}"
    if len(identity) > 256:
        raise ValueError("CSV identity exceeds 256 characters")  # noqa: TRY003
    return identity


class CSVDocumentInput(BaseModel):
    document_id: str
    primary_key: str
    content: bytes


class CSVRowInput(BaseModel):
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]

    @model_validator(mode="after")
    def validate_row(self):
        csv_row_source_id(self.document_id, self.primary_key_value)
        if not self.columns or any(not c.strip() for c in self.columns) or len(set(self.columns)) != len(self.columns):
            raise ValueError("CSV headers must be nonempty and unique")  # noqa: TRY003
        if self.primary_key not in self.columns or len(self.columns) != len(self.values):
            raise ValueError("CSV key or width mismatch")  # noqa: TRY003
        if self.values[self.columns.index(self.primary_key)] != self.primary_key_value:
            raise ValueError("CSV primary key value mismatch")  # noqa: TRY003
        return self


class CSVRowSource(Source):
    source_id: str
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    if not value.document_id or value.document_id != value.document_id.strip() or not value.primary_key:
        raise ValueError("Invalid document or primary key")  # noqa: TRY003
    try:
        reader = csv.reader(io.StringIO(value.content.decode("utf-8-sig"), newline=""), strict=True)
        columns = tuple(next(reader, ()))
        if not columns or any(not c.strip() for c in columns) or len(set(columns)) != len(columns):
            raise ValueError("CSV headers must be nonempty and unique")  # noqa: TRY003
        if value.primary_key not in columns:
            raise ValueError("Primary key is absent from header")  # noqa: TRY003
        rows = []
        seen = set()
        for fields in reader:
            if not fields:
                continue
            if len(fields) != len(columns):
                raise ValueError("CSV record width mismatch")  # noqa: TRY003
            key = fields[columns.index(value.primary_key)]
            if key in seen:
                raise ValueError("Duplicate primary key")  # noqa: TRY003
            rows.append(
                CSVRowInput(
                    document_id=value.document_id,
                    primary_key=value.primary_key,
                    primary_key_value=key,
                    columns=columns,
                    values=tuple(fields),
                )
            )
            seen.add(key)
        return tuple(rows)
    except (UnicodeError, csv.Error) as error:
        raise ValueError("Invalid UTF-8 CSV") from error  # noqa: TRY003


class _CSVProjection:
    name = "powercontext.text-evidence"
    version = "1"
    source_class = CSVRowSource
    output_class = TextEvidence

    def project(self, source: CSVRowSource):
        row = dict(zip(source.columns, source.values, strict=True))
        return TextEvidence(
            source_type="csv-row",
            source_id=source.source_id,
            content=json.dumps(row, ensure_ascii=False, separators=(",", ":")),
            metadata={
                "document_id": source.document_id,
                "primary_key": source.primary_key,
                "primary_key_value": source.primary_key_value,
                "columns": list(source.columns),
                "row": row,
            },
        )


class _CSVDefinition:
    name = "csv-row"
    version = "1"
    input_class = CSVRowInput
    source_class = CSVRowSource
    projections = (_CSVProjection(),)

    async def resolve(self, value: CSVRowInput):
        identity = csv_row_source_id(value.document_id, value.primary_key_value)
        return CSVRowSource(
            name=identity, source_id=identity, materialization=SourceMaterialization.CAPTURED, **value.model_dump()
        )

    async def read(self, source: CSVRowSource):
        return CSVRowInput.model_validate(source.model_dump())


CSV_ROW_SOURCE_DEFINITION = _CSVDefinition()
