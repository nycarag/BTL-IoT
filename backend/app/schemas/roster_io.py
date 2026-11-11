"""Schemas for roster import/export."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class ImportError(BaseModel):
    row: int
    field: str | None = None
    message: str


class ImportResult(BaseModel):
    mode: str
    total_rows: int
    valid_rows: int
    created: int
    updated: int
    skipped: int
    filtered_out: int = 0
    errors: list[ImportError] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
