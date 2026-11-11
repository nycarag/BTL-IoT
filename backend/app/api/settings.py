"""Router cấu hình hệ thống (Settings API)."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security import verify_token
from app.database import get_db
from app.services import session_lifecycle
from app.services.audit import client_ip, log_action

router = APIRouter()


class AttendanceSettingsInput(BaseModel):
    late_after_minutes: int


@router.get("/settings/attendance")
def get_attendance_settings(
    _: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Lấy ngưỡng thời gian tính đi muộn (phút) hiện hành."""
    return {"late_after_minutes": session_lifecycle.get_late_minutes(db)}


@router.put("/settings/attendance")
def update_attendance_settings(
    payload: AttendanceSettingsInput,
    request: Request,
    username: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Cập nhật ngưỡng thời gian tính đi muộn (1..120 phút) và tính lại toàn bộ trạng thái điểm danh."""
    old_val = session_lifecycle.get_late_minutes(db)
    try:
        recomputed = session_lifecycle.set_late_minutes(db, payload.late_after_minutes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    log_action(
        db,
        username,
        "settings.update",
        detail={
            "old": old_val,
            "new": payload.late_after_minutes,
            "recomputed": recomputed,
        },
        ip_address=client_ip(request),
        commit=False,
    )
    db.commit()
    return {
        "late_after_minutes": payload.late_after_minutes,
        "recomputed": recomputed,
    }
