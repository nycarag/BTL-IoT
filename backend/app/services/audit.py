"""Audit logging service for tracking administrative and user actions."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.school import AuditLog


def log_action(
    db: Session,
    actor: str,
    action: str,
    *,
    target: str | None = None,
    detail: dict | None = None,
    ip_address: str | None = None,
    commit: bool = True,
) -> AuditLog:
    """Ghi nhật ký hoạt động hệ thống. KHÔNG bao giờ ghi mật khẩu, token hay thông tin nhạy cảm vào detail."""
    detail_str: str | None = None
    if detail is not None:
        detail_str = json.dumps(detail, ensure_ascii=False, default=str)[:4000]

    safe_actor = (actor or "")[:255]
    safe_target = target[:255] if target is not None else None
    safe_action = (action or "")[:64]
    safe_ip = ip_address[:64] if ip_address is not None else None

    entry = AuditLog(
        actor=safe_actor,
        action=safe_action,
        target=safe_target,
        detail=detail_str,
        ip_address=safe_ip,
    )
    db.add(entry)
    if commit:
        db.commit()
        db.refresh(entry)
    else:
        db.flush()
    return entry


def client_ip(request: Any) -> str | None:
    """Trả về request.client.host nếu có, ngược lại None. Không tin header X-Forwarded-For."""
    if request is None:
        return None
    client = getattr(request, "client", None)
    if client and getattr(client, "host", None):
        return str(client.host)
    return None
