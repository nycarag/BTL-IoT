"""Module quản lý vòng đời buổi điểm danh (session lifecycle), ngưỡng đi muộn và tự động ghi vắng."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.school import AppSetting, Attendance, AttendanceSession, ClassSchedule, Student

VN_TZ = timezone(timedelta(hours=7), "ICT")


def _to_aware_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_late_minutes(db: Session) -> int:
    """Đọc ngưỡng đi muộn (phút) từ AppSetting 'late_after_minutes', fallback sang settings.late_after_minutes."""
    setting = db.get(AppSetting, "late_after_minutes")
    if setting and setting.value:
        try:
            return int(setting.value)
        except ValueError:
            pass
    return settings.late_after_minutes


def late_reference_start(db: Session, session: AttendanceSession) -> datetime | None:
    """Lấy mốc thời gian bắt đầu dùng để tính đi muộn (aware UTC).

    Ưu tiên start_at của ClassSchedule liên kết với session, nếu không có thì lấy session.starts_at.
    """
    sched = db.scalar(select(ClassSchedule).where(ClassSchedule.session_id == session.id))
    dt = sched.start_at if sched and sched.start_at is not None else session.starts_at
    return _to_aware_utc(dt)


def status_for(checked_at: datetime, start: datetime | None, minutes: int) -> Literal["present", "late"]:
    """Xác định trạng thái 'present' (đúng giờ) hoặc 'late' (đi muộn).

    'late' khi checked_at > start + minutes phút. Nếu start là None thì trả về 'present'.
    """
    if start is None:
        return "present"
    c_dt = _to_aware_utc(checked_at)
    s_dt = _to_aware_utc(start)
    if c_dt is None or s_dt is None:
        return "present"
    if c_dt > s_dt + timedelta(minutes=minutes):
        return "late"
    return "present"


def recompute_statuses(db: Session, minutes: int) -> int:
    """Duyệt các Attendance có status trong ('present', 'late'), tính lại bằng status_for.

    Bản ghi status 'absent' được giữ nguyên. Trả về số bản ghi thay đổi trạng thái.
    """
    attendances = db.scalars(
        select(Attendance).where(Attendance.status.in_(["present", "late"]))
    ).all()
    if not attendances:
        return 0

    starts_cache: dict[int, datetime | None] = {}
    changed = 0

    for att in attendances:
        if att.session_id not in starts_cache:
            sess = db.get(AttendanceSession, att.session_id)
            starts_cache[att.session_id] = late_reference_start(db, sess) if sess else None

        ref_start = starts_cache[att.session_id]
        new_status = status_for(att.checked_at, ref_start, minutes)
        if att.status != new_status:
            att.status = new_status
            changed += 1

    return changed


def set_late_minutes(db: Session, minutes: int) -> int:
    """Cập nhật ngưỡng đi muộn vào AppSetting, tính lại trạng thái các bản ghi và trả về số bản ghi đổi.

    minutes phải là số nguyên trong khoảng 1..120, nếu sai raise ValueError.
    """
    if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes < 1 or minutes > 120:
        raise ValueError("Ngưỡng đi muộn phải từ 1 đến 120 phút")

    setting = db.get(AppSetting, "late_after_minutes")
    now_utc = datetime.now(timezone.utc)
    if not setting:
        setting = AppSetting(key="late_after_minutes", value=str(minutes), updated_at=now_utc)
        db.add(setting)
    else:
        setting.value = str(minutes)
        setting.updated_at = now_utc

    db.flush()
    return recompute_statuses(db, minutes)


def ensure_session_for_schedule(db: Session, schedule: ClassSchedule) -> AttendanceSession:
    """Trả về buổi điểm danh liên kết với lịch; nếu chưa có thì tạo ca draft mới."""
    if schedule.session_id:
        existing = db.get(AttendanceSession, schedule.session_id)
        if existing:
            return existing

    s_utc = _to_aware_utc(schedule.start_at)
    s_vn = s_utc.astimezone(VN_TZ) if s_utc else datetime.now(VN_TZ)
    date_str = s_vn.strftime("%d/%m/%Y")
    session_title = f"{schedule.title} · {date_str}"

    sess = AttendanceSession(
        class_id=schedule.class_id,
        title=session_title,
        status="draft",
    )
    db.add(sess)
    db.flush()
    schedule.session_id = sess.id
    return sess


def mark_absent(db: Session, session: AttendanceSession, closed_at: datetime) -> int:
    """Tạo bản ghi vắng mặt cho sinh viên của lớp chưa có bản ghi điểm danh trong ca."""
    class_students = db.scalars(
        select(Student.id).where(Student.class_id == session.class_id)
    ).all()
    if not class_students:
        return 0

    attended_student_ids = set(
        db.scalars(
            select(Attendance.student_id).where(Attendance.session_id == session.id)
        ).all()
    )

    c_at = _to_aware_utc(closed_at)
    added = 0
    for sid in class_students:
        if sid not in attended_student_ids:
            att = Attendance(
                session_id=session.id,
                student_id=sid,
                status="absent",
                device_id=None,
                verification="auto-absent",
                checked_at=c_at,
            )
            db.add(att)
            added += 1

    if added:
        db.flush()
    return added


def close_session(db: Session, session: AttendanceSession, now: datetime) -> int:
    """Đóng ca điểm danh và tự động ghi vắng cho sinh viên chưa điểm danh."""
    if session.status != "open":
        raise ValueError("Only an open session can be closed")

    n_utc = _to_aware_utc(now)
    session.status = "closed"
    session.ends_at = n_utc
    absent_count = mark_absent(db, session, n_utc)
    db.flush()
    return absent_count


def open_session(db: Session, session: AttendanceSession, now: datetime) -> None:
    """Mở ca điểm danh, đồng thời đóng các ca đang mở khác cùng lớp (kèm ghi vắng)."""
    if session.status == "closed":
        raise ValueError("Closed session cannot be reopened")

    n_utc = _to_aware_utc(now)

    # Đóng mọi ca open khác cùng lớp (gọi close_session để ghi vắng)
    open_others = db.scalars(
        select(AttendanceSession).where(
            AttendanceSession.class_id == session.class_id,
            AttendanceSession.status == "open",
            AttendanceSession.id != session.id,
        )
    ).all()
    for other in open_others:
        close_session(db, other, n_utc)

    session.status = "open"
    session.starts_at = session.starts_at or n_utc
    db.flush()
