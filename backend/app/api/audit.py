"""Router for viewing administrative audit logs."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import verify_token
from app.database import get_db
from app.models.school import AuditLog

router = APIRouter()


class AuditLogResponse(BaseModel):
    """Schema phản hồi nhật ký quản trị."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    actor: str
    action: str
    target: str | None = None
    detail: Any = None
    ip_address: str | None = None
    created_at: datetime


@router.get("/audit-logs", response_model=list[AuditLogResponse])
def list_audit_logs(
    action: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Lấy danh sách nhật ký quản trị với bộ lọc action, phân trang limit/offset."""
    query = select(AuditLog)
    if action:
        action_clean = action.strip()
        if action_clean.endswith("."):
            query = query.where(AuditLog.action.startswith(action_clean))
        elif action_clean:
            query = query.where(AuditLog.action == action_clean)

    query = query.order_by(AuditLog.id.desc()).offset(offset).limit(limit)
    rows = db.scalars(query).all()

    results: list[dict[str, Any]] = []
    for row in rows:
        parsed_detail: Any = None
        if row.detail:
            try:
                parsed_detail = json.loads(row.detail)
            except Exception:
                parsed_detail = row.detail

        created_at = row.created_at
        if created_at is not None and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        results.append({
            "id": row.id,
            "actor": row.actor,
            "action": row.action,
            "target": row.target,
            "detail": parsed_detail,
            "ip_address": row.ip_address,
            "created_at": created_at,
        })
    return results
