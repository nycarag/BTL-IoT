"""SQLite write transaction serializes attendance against session close."""
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.models import Attendance, AttendanceSession, ClassSchedule, Student
from app.models.school import DeviceConfig, FaceReference
from app.services import session_lifecycle


def record_attendance(db, session, student, *, device_id, verification):
    session_id, student_id = session.id, student.id
    db.rollback()
    if db.bind.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
    session = db.get(AttendanceSession, session_id, populate_existing=True)
    student = db.get(Student, student_id, populate_existing=True)
    if session is None or session.status != "open":
        db.rollback()
        raise ValueError("Attendance session is not open")
    if student is None or student.class_id != session.class_id:
        db.rollback()
        raise ValueError("Student does not belong to this class")
    if device_id is not None:
        config = db.get(DeviceConfig, device_id, populate_existing=True)
        reference = db.get(FaceReference, student_id, populate_existing=True)
        if config is None or config.session_id != session_id or reference is None:
            db.rollback()
            raise ValueError("Device assignment or biometric enrollment changed; retry verification")
    existing = db.scalar(select(Attendance).where(Attendance.session_id == session_id, Attendance.student_id == student_id))
    if existing:
        db.commit()
        return existing, False
    now = datetime.now(timezone.utc)
    ref_start = session_lifecycle.late_reference_start(db, session)
    start = ref_start if ref_start is not None else now
    late_minutes = session_lifecycle.get_late_minutes(db)
    att_status = session_lifecycle.status_for(now, start, late_minutes)
    row = Attendance(
        session_id=session_id,
        student_id=student_id,
        checked_at=now,
        status=att_status,
        device_id=device_id,
        verification=verification,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(Attendance).where(Attendance.session_id == session_id, Attendance.student_id == student_id))
        if existing:
            return existing, False
        raise
    return row, True
