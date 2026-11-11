"""Tests for session lifecycle, late threshold and auto-absent service (Task K01)."""

import os
os.environ["ADMIN_PASSWORD"] = "test-password-only"
os.environ["DEVICE_TOKEN"] = "test-device-only"
os.environ["FRAME_INTERVAL_SECONDS"] = "0"

from datetime import datetime, timedelta, timezone
import tempfile
import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.school import AppSetting, Attendance, AttendanceSession, ClassRoom, ClassSchedule, Student
from app.services import session_lifecycle

VN_TZ = timezone(timedelta(hours=7), "ICT")


class TestSessionLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{self.temp.name}/test.db",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(self.engine, expire_on_commit=False)

        with self.factory() as db:
            self.class1 = ClassRoom(code="D23CTAT01-B", name="Lớp 1")
            self.class2 = ClassRoom(code="D23CTAT02-B", name="Lớp 2")
            db.add_all([self.class1, self.class2])
            db.flush()

            self.s1 = Student(student_code="B23DCAT001", name="SV 1", class_id=self.class1.id)
            self.s2 = Student(student_code="B23DCAT002", name="SV 2", class_id=self.class1.id)
            self.s3 = Student(student_code="B23DCAT003", name="SV Khác Lớp", class_id=self.class2.id)
            db.add_all([self.s1, self.s2, self.s3])
            db.commit()

            self.c1_id = self.class1.id
            self.c2_id = self.class2.id
            self.s1_id = self.s1.id
            self.s2_id = self.s2.id
            self.s3_id = self.s3.id

    def tearDown(self):
        self.engine.dispose()
        self.temp.cleanup()

    def test_default_late_minutes_is_15(self):
        """Mặc định 15 phút khi chưa có AppSetting."""
        with self.factory() as db:
            minutes = session_lifecycle.get_late_minutes(db)
            self.assertEqual(minutes, 15)

    def test_set_and_get_late_minutes(self):
        """Set 20 phút thì get_late_minutes trả ra 20."""
        with self.factory() as db:
            recomputed = session_lifecycle.set_late_minutes(db, 20)
            self.assertEqual(recomputed, 0)
            db.commit()

            minutes = session_lifecycle.get_late_minutes(db)
            self.assertEqual(minutes, 20)

    def test_set_invalid_late_minutes_raises_value_error(self):
        """Ngưỡng ngoài 1..120 phải raise ValueError tiếng Việt."""
        with self.factory() as db:
            with self.assertRaises(ValueError):
                session_lifecycle.set_late_minutes(db, 0)
            with self.assertRaises(ValueError):
                session_lifecycle.set_late_minutes(db, 121)
            with self.assertRaises(ValueError):
                session_lifecycle.set_late_minutes(db, -5)

    def test_late_reference_start(self):
        """Ưu tiên start_at của ClassSchedule gắn với ca, trả aware UTC."""
        now_utc = datetime.now(timezone.utc)
        sched_start = now_utc - timedelta(hours=1)
        with self.factory() as db:
            sess = AttendanceSession(class_id=self.c1_id, title="Test Sess", status="open", starts_at=now_utc)
            db.add(sess)
            db.flush()

            sched = ClassSchedule(
                class_id=self.c1_id,
                title="Lịch học",
                start_at=sched_start,
                end_at=now_utc + timedelta(hours=1),
                session_id=sess.id,
            )
            db.add(sched)
            db.commit()
            db.refresh(sess)

            ref = session_lifecycle.late_reference_start(db, sess)
            self.assertIsNotNone(ref)
            self.assertEqual(ref.tzinfo, timezone.utc)
            self.assertEqual(ref, sched_start)

    def test_status_for(self):
        """status_for tính đúng present/late và fallback present khi start là None."""
        base = datetime(2026, 11, 11, 8, 0, tzinfo=timezone.utc)
        self.assertEqual(session_lifecycle.status_for(base + timedelta(minutes=10), base, 15), "present")
        self.assertEqual(session_lifecycle.status_for(base + timedelta(minutes=15), base, 15), "present")
        self.assertEqual(session_lifecycle.status_for(base + timedelta(minutes=16), base, 15), "late")
        self.assertEqual(session_lifecycle.status_for(base, None, 15), "present")

    def test_recompute_statuses(self):
        """recompute_statuses đổi đúng present <-> late và không chạm vào absent."""
        start = datetime(2026, 11, 11, 8, 0, tzinfo=timezone.utc)
        with self.factory() as db:
            sess = AttendanceSession(class_id=self.c1_id, title="Ca 1", status="open", starts_at=start)
            db.add(sess)
            db.flush()

            sched = ClassSchedule(
                class_id=self.c1_id,
                title="Lịch 1",
                start_at=start,
                end_at=start + timedelta(hours=2),
                session_id=sess.id,
            )
            db.add(sched)
            db.flush()

            # SV 1 check-in lúc 8:18 (late với ngưỡng 15, present với ngưỡng 20)
            att1 = Attendance(session_id=sess.id, student_id=self.s1_id, checked_at=start + timedelta(minutes=18), status="late")
            # SV 2 là absent
            att2 = Attendance(session_id=sess.id, student_id=self.s2_id, checked_at=start + timedelta(hours=2), status="absent")
            db.add_all([att1, att2])
            db.commit()

            # Đổi ngưỡng sang 20: att1 chuyển từ late -> present, att2 giữ nguyên absent
            changed = session_lifecycle.set_late_minutes(db, 20)
            self.assertEqual(changed, 1)
            db.commit()

            db.refresh(att1)
            db.refresh(att2)
            self.assertEqual(att1.status, "present")
            self.assertEqual(att2.status, "absent")

            # Đổi ngưỡng về 10: att1 chuyển lại thành late
            changed2 = session_lifecycle.set_late_minutes(db, 10)
            self.assertEqual(changed2, 1)
            db.commit()
            db.refresh(att1)
            self.assertEqual(att1.status, "late")

    def test_ensure_session_for_schedule(self):
        """Tạo ca draft khớp format title và gán session_id vào schedule."""
        start_utc = datetime(2026, 11, 20, 6, 0, tzinfo=timezone.utc)  # 13:00 giờ VN
        with self.factory() as db:
            sched = ClassSchedule(
                class_id=self.c1_id,
                title="IoT Buổi 1",
                start_at=start_utc,
                end_at=start_utc + timedelta(hours=2),
            )
            db.add(sched)
            db.flush()

            sess = session_lifecycle.ensure_session_for_schedule(db, sched)
            self.assertEqual(sess.status, "draft")
            self.assertEqual(sess.class_id, self.c1_id)
            self.assertIn("IoT Buổi 1 · 20/11/2026", sess.title)
            self.assertEqual(sched.session_id, sess.id)

            # Gọi lại lần 2 trả đúng ca cũ
            sess2 = session_lifecycle.ensure_session_for_schedule(db, sched)
            self.assertEqual(sess2.id, sess.id)

    def test_mark_absent_and_unique_constraint(self):
        """mark_absent tạo bản ghi vắng cho SV chưa có điểm danh, bỏ qua lớp khác, không trùng."""
        now = datetime.now(timezone.utc)
        with self.factory() as db:
            sess = AttendanceSession(class_id=self.c1_id, title="Ca Kiểm Tra Vắng", status="open", starts_at=now)
            db.add(sess)
            db.flush()

            # SV 1 đã có mặt
            att1 = Attendance(session_id=sess.id, student_id=self.s1_id, checked_at=now, status="present")
            db.add(att1)
            db.commit()

            # Gọi mark_absent: chỉ tạo absent cho SV 2 (SV 3 thuộc lớp 2 bị bỏ qua)
            added = session_lifecycle.mark_absent(db, sess, now)
            self.assertEqual(added, 1)
            db.commit()

            atts = db.scalars(select(Attendance).where(Attendance.session_id == sess.id)).all()
            self.assertEqual(len(atts), 2)
            absent_record = next(a for a in atts if a.student_id == self.s2_id)
            self.assertEqual(absent_record.status, "absent")
            self.assertEqual(absent_record.verification, "auto-absent")

            # Gọi lại lần nữa -> 0 bản ghi mới (không vi phạm unique constraint)
            added_again = session_lifecycle.mark_absent(db, sess, now)
            self.assertEqual(added_again, 0)

    def test_open_and_close_session_lifecycle(self):
        """Kiểm tra quy tắc mở ca, đóng ca và tự động đóng ca cũ cùng lớp."""
        now = datetime.now(timezone.utc)
        with self.factory() as db:
            sess_a = AttendanceSession(class_id=self.c1_id, title="Ca A", status="draft")
            sess_b = AttendanceSession(class_id=self.c1_id, title="Ca B", status="draft")
            db.add_all([sess_a, sess_b])
            db.commit()

            # Mở ca A
            session_lifecycle.open_session(db, sess_a, now)
            self.assertEqual(sess_a.status, "open")
            db.commit()

            # Mở ca B cùng lớp -> ca A tự động bị đóng và ghi vắng
            now_later = now + timedelta(hours=1)
            session_lifecycle.open_session(db, sess_b, now_later)
            db.commit()

            db.refresh(sess_a)
            db.refresh(sess_b)
            self.assertEqual(sess_a.status, "closed")
            self.assertEqual(sess_b.status, "open")

            # Ca A có 2 bản ghi absent (SV 1 và SV 2)
            a_absents = db.scalars(select(Attendance).where(Attendance.session_id == sess_a.id, Attendance.status == "absent")).all()
            self.assertEqual(len(a_absents), 2)

            # Mở lại ca A đã closed -> ValueError
            with self.assertRaises(ValueError):
                session_lifecycle.open_session(db, sess_a, now)

            # Đóng ca A lần nữa -> ValueError (chỉ đóng ca đang open)
            with self.assertRaises(ValueError):
                session_lifecycle.close_session(db, sess_a, now)

            # Đóng ca B -> thành công
            absent_b = session_lifecycle.close_session(db, sess_b, now_later + timedelta(hours=2))
            self.assertEqual(absent_b, 2)
            self.assertEqual(sess_b.status, "closed")
