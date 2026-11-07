"""Tests for attendance late status calculated from class schedule start time."""

from datetime import datetime, timedelta, timezone
import tempfile
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.school import AttendanceSession, ClassRoom, ClassSchedule, Student
from app.services.attendance_service import record_attendance


class TestScheduleLate(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{self.temp.name}/test.db",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(self.engine, expire_on_commit=False)

        with self.factory() as db:
            self.classroom = ClassRoom(code="D23CTAT01-B", name="Lớp An Toàn 1")
            db.add(self.classroom)
            db.flush()

            self.student = Student(
                student_code="B23DCAT001",
                name="Nguyễn Văn A",
                class_id=self.classroom.id,
            )
            db.add(self.student)
            db.commit()
            db.refresh(self.classroom)
            db.refresh(self.student)

    def tearDown(self):
        self.engine.dispose()
        self.temp.cleanup()

    def test_session_with_schedule_started_30_minutes_ago_is_late(self):
        """Buổi có lịch bắt đầu cách đây 30 phút (lớn hơn LATE_AFTER_MINUTES=15), vừa được mở -> late."""
        now = datetime.now(timezone.utc)
        with self.factory() as db:
            # Buổi vừa mới được mở (starts_at = now)
            session = AttendanceSession(
                class_id=self.classroom.id,
                title="Buổi kiểm tra đi muộn",
                status="open",
                starts_at=now,
            )
            db.add(session)
            db.flush()

            # Lịch học đã bắt đầu từ 30 phút trước
            schedule = ClassSchedule(
                class_id=self.classroom.id,
                title="Lịch học bắt đầu 30 phút trước",
                start_at=now - timedelta(minutes=30),
                end_at=now + timedelta(hours=1),
                session_id=session.id,
            )
            db.add(schedule)
            db.commit()
            db.refresh(session)

            att, created = record_attendance(
                db,
                session,
                self.student,
                device_id=None,
                verification="manual",
            )
            self.assertTrue(created)
            self.assertEqual(att.status, "late")

    def test_session_with_schedule_started_5_minutes_ago_is_present(self):
        """Buổi có lịch bắt đầu cách đây 5 phút (nhỏ hơn LATE_AFTER_MINUTES=15) -> present."""
        now = datetime.now(timezone.utc)
        with self.factory() as db:
            session = AttendanceSession(
                class_id=self.classroom.id,
                title="Buổi kiểm tra đúng giờ",
                status="open",
                starts_at=now,
            )
            db.add(session)
            db.flush()

            schedule = ClassSchedule(
                class_id=self.classroom.id,
                title="Lịch học bắt đầu 5 phút trước",
                start_at=now - timedelta(minutes=5),
                end_at=now + timedelta(hours=1),
                session_id=session.id,
            )
            db.add(schedule)
            db.commit()
            db.refresh(session)

            att, created = record_attendance(
                db,
                session,
                self.student,
                device_id=None,
                verification="manual",
            )
            self.assertTrue(created)
            self.assertEqual(att.status, "present")

    def test_session_without_schedule_opened_now_is_present(self):
        """Buổi không có lịch, vừa mở -> present (hành vi cũ)."""
        now = datetime.now(timezone.utc)
        with self.factory() as db:
            session = AttendanceSession(
                class_id=self.classroom.id,
                title="Buổi không có lịch",
                status="open",
                starts_at=now,
            )
            db.add(session)
            db.commit()
            db.refresh(session)

            att, created = record_attendance(
                db,
                session,
                self.student,
                device_id=None,
                verification="manual",
            )
            self.assertTrue(created)
            self.assertEqual(att.status, "present")

    def test_session_without_schedule_opened_30_minutes_ago_is_late(self):
        """Buổi không có lịch, mở cách đây 30 phút -> late (bảo lưu hành vi cũ)."""
        now = datetime.now(timezone.utc)
        with self.factory() as db:
            session = AttendanceSession(
                class_id=self.classroom.id,
                title="Buổi không có lịch mở lâu",
                status="open",
                starts_at=now - timedelta(minutes=30),
            )
            db.add(session)
            db.commit()
            db.refresh(session)

            att, created = record_attendance(
                db,
                session,
                self.student,
                device_id=None,
                verification="manual",
            )
            self.assertTrue(created)
            self.assertEqual(att.status, "late")


if __name__ == "__main__":
    unittest.main()
