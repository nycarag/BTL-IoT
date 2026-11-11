"""Tiến trình tự động mở và đóng ca điểm danh theo lịch học (Auto-session worker)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import SessionLocal
from app.models.school import AttendanceSession, ClassSchedule
from app.services import session_lifecycle
from app.services.websocket import manager

logger = logging.getLogger(__name__)


def _to_utc(dt: datetime) -> datetime:
    """Chuyển đổi datetime sang aware UTC (nếu naive trong SQLite thì gán tzinfo=UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def tick(db: Session, now: datetime) -> list[tuple[int, str]]:
    """Thực hiện một nhịp kiểm tra lịch học và mở/đóng ca điểm danh tự động (Quy tắc a, b, c).

    - a) Lịch có start_at <= now < end_at:
         Tạo ca nếu chưa có (ensure_session_for_schedule);
         Nếu ca đang 'draft' thì mở (open_session).
         Nếu ca đã 'closed' (giảng viên đóng sớm) thì giữ nguyên, không mở lại.
    - b) Lịch có end_at <= now mà ca còn 'open':
         Đóng ca (close_session) và tự động ghi vắng cho sinh viên chưa có mặt.
    - c) Lịch đã qua (end_at <= now) mà chưa từng có ca:
         Không tạo, không ghi vắng.

    Trả về danh sách (session_id, 'open' | 'closed') các ca đã thay đổi trạng thái.
    """
    now_utc = _to_utc(now)
    schedules = list(db.scalars(select(ClassSchedule)).all())
    if not schedules:
        return []

    changed: list[tuple[int, str]] = []

    # 1. Xử lý đóng ca trước (Quy tắc b: lịch có end_at <= now mà ca còn 'open')
    for sched in schedules:
        end_utc = _to_utc(sched.end_at)
        if end_utc <= now_utc and sched.session_id:
            try:
                db.rollback()
                if db.bind.dialect.name == "sqlite":
                    db.execute(text("BEGIN IMMEDIATE"))
                sess = db.get(AttendanceSession, sched.session_id)
                if sess and sess.status == "open":
                    session_lifecycle.close_session(db, sess, now_utc)
                    db.commit()
                    changed.append((sess.id, "closed"))
                else:
                    db.rollback()
            except Exception:
                db.rollback()
                logger.exception("Lỗi khi tự động đóng ca cho lịch #%s", sched.id)

    # 2. Xử lý mở ca (Quy tắc a: lịch có start_at <= now < end_at)
    for sched in schedules:
        start_utc = _to_utc(sched.start_at)
        end_utc = _to_utc(sched.end_at)
        if start_utc <= now_utc < end_utc:
            try:
                db.rollback()
                if db.bind.dialect.name == "sqlite":
                    db.execute(text("BEGIN IMMEDIATE"))
                # Tạo ca nếu chưa có
                sess = session_lifecycle.ensure_session_for_schedule(db, sched)
                if sess.status == "draft":
                    session_lifecycle.open_session(db, sess, now_utc)
                    db.commit()
                    changed.append((sess.id, "open"))
                else:
                    db.commit()
            except Exception:
                db.rollback()
                logger.exception("Lỗi khi tự động mở ca cho lịch #%s", sched.id)

    return changed


def _run_tick() -> list[tuple[int, str]]:
    """Helper mở DB session qua SessionLocal và gọi tick."""
    with SessionLocal() as db:
        return tick(db, datetime.now(timezone.utc))


async def run_forever() -> None:
    """Vòng lặp chạy nền của tiến trình tự động mở/đóng ca.

    Gọi tick qua asyncio.to_thread để tránh nghẽn luồng sự kiện (event loop) của FastAPI khi thực hiện
    các truy vấn CSDL đồng bộ trên SQLite. Broadcast sự kiện qua WebSocket manager khi có ca đổi trạng thái.
    """
    interval = settings.auto_session_interval_seconds
    logger.info("Tiến trình tự động mở/đóng ca đã khởi chạy (chu kỳ: %d giây)", interval)

    while True:
        try:
            # Chạy tick trong thread pool riêng để không block asyncio event loop
            events = await asyncio.to_thread(_run_tick)
            for session_id, new_status in events:
                logger.info("Auto-session: Buổi học #%s chuyển sang trạng thái '%s'", session_id, new_status)
                await manager.broadcast(session_id, {"type": "session", "status": new_status})
        except asyncio.CancelledError:
            logger.info("Tiến trình auto-session nhận tín hiệu dừng (Cancelled)")
            raise
        except Exception:
            logger.exception("Lỗi không mong muốn trong vòng lặp auto-session")

        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("Tiến trình auto-session nhận tín hiệu dừng khi đang chờ chu kỳ tiếp theo")
            raise
