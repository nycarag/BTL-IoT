"""Tests for auto-session worker and scheduled open/close lifecycle (Task K05)."""

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

os.environ["ADMIN_PASSWORD"] = "test-password-only"
os.environ["DEVICE_TOKEN"] = "test-device-only"
os.environ["FRAME_INTERVAL_SECONDS"] = "0"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import create_app
from app.models.school import Attendance, AttendanceSession, ClassRoom, ClassSchedule, Student
from app.services import auto_session, session_lifecycle

VN_TZ = timezone(timedelta(hours=7), "ICT")


class TestAutoSession(unittest.TestCase):
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

            self.s1 = Student(student_code="B23DCAT001", name="Nguyễn Văn A", class_id=self.classroom.id)
            self.s2 = Student(student_code="B23DCAT002", name="Trần Thị B", class_id=self.classroom.id)
            self.s3 = Student(student_code="B23DCAT003", name="Lê Văn C", class_id=self.classroom.id)
            db.add_all([self.s1, self.s2, self.s3])
            db.commit()

            self.class_id = self.classroom.id
            self.s1_id = self.s1.id
            self.s2_id = self.s2.id
            self.s3_id = self.s3.id

    def tearDown(self):
        self.engine.dispose()
        self.temp.cleanup()

    def test_auto_session_tick_lifecycle_and_early_close(self):
        """Lịch 13:00-15:00: 12:59 không làm gì; 13:00 mở ca; 13:30 không tạo lại; 14:00 đóng sớm thì 14:10 không mở lại."""
        start_vn = datetime(2026, 11, 20, 13, 0, tzinfo=VN_TZ)
        end_vn = datetime(2026, 11, 20, 15, 0, tzinfo=VN_TZ)
        start_utc = start_vn.astimezone(timezone.utc)
        end_utc = end_vn.astimezone(timezone.utc)

        with self.factory() as db:
            sched = ClassSchedule(
                class_id=self.class_id,
                title="IoT và ứng dụng",
                start_at=start_utc,
                end_at=end_utc,
            )
            db.add(sched)
            db.commit()

            # 1. 12:59 -> không làm gì
            now_1259 = datetime(2026, 11, 20, 12, 59, tzinfo=VN_TZ)
            events = auto_session.tick(db, now_1259)
            self.assertEqual(events, [])
            self.assertIsNone(sched.session_id)

            # 2. 13:00 -> tạo ca và mở
            now_1300 = datetime(2026, 11, 20, 13, 0, tzinfo=VN_TZ)
            events = auto_session.tick(db, now_1300)
            self.assertEqual(len(events), 1)
            sess_id, status = events[0]
            self.assertEqual(status, "open")

            db.refresh(sched)
            self.assertEqual(sched.session_id, sess_id)
            sess = db.get(AttendanceSession, sess_id)
            self.assertEqual(sess.status, "open")

            # 3. 13:30 gọi lại -> không tạo ca thứ hai
            now_1330 = datetime(2026, 11, 20, 13, 30, tzinfo=VN_TZ)
            events_1330 = auto_session.tick(db, now_1330)
            self.assertEqual(events_1330, [])
            all_sessions = db.scalars(select(AttendanceSession)).all()
            self.assertEqual(len(all_sessions), 1)

            # 4. Giảng viên đóng sớm lúc 14:00
            now_1400 = datetime(2026, 11, 20, 14, 0, tzinfo=VN_TZ)
            session_lifecycle.close_session(db, sess, now_1400.astimezone(timezone.utc))
            db.commit()
            db.refresh(sess)
            self.assertEqual(sess.status, "closed")

            # 5. Tick lúc 14:10 -> không mở lại
            now_1410 = datetime(2026, 11, 20, 14, 10, tzinfo=VN_TZ)
            events_1410 = auto_session.tick(db, now_1410)
            self.assertEqual(events_1410, [])
            db.refresh(sess)
            self.assertEqual(sess.status, "closed")

    def test_auto_session_close_at_end_time_with_absent(self):
        """Tick đúng end_at -> ca closed, sinh viên chưa điểm danh có bản ghi absent."""
        start_vn = datetime(2026, 11, 21, 15, 0, tzinfo=VN_TZ)
        end_vn = datetime(2026, 11, 21, 17, 0, tzinfo=VN_TZ)

        with self.factory() as db:
            sched = ClassSchedule(
                class_id=self.class_id,
                title="Lập trình mạng",
                start_at=start_vn.astimezone(timezone.utc),
                end_at=end_vn.astimezone(timezone.utc),
            )
            db.add(sched)
            db.commit()

            # Mở ca lúc 15:00
            auto_session.tick(db, start_vn)
            db.refresh(sched)
            sess = db.get(AttendanceSession, sched.session_id)
            self.assertEqual(sess.status, "open")

            # SV 1 điểm danh
            att1 = Attendance(
                session_id=sess.id,
                student_id=self.s1_id,
                checked_at=start_vn.astimezone(timezone.utc),
                status="present",
                verification="face+pad",
            )
            db.add(att1)
            db.commit()

            # Tick đúng 17:00 (hết giờ buổi học)
            events_1700 = auto_session.tick(db, end_vn)
            self.assertEqual(events_1700, [(sess.id, "closed")])

            db.refresh(sess)
            self.assertEqual(sess.status, "closed")

            # SV 2 và SV 3 có bản ghi absent
            records = db.scalars(select(Attendance).where(Attendance.session_id == sess.id)).all()
            self.assertEqual(len(records), 3)

            present_records = [r for r in records if r.status in ("present", "late")]
            absent_records = [r for r in records if r.status == "absent"]
            self.assertEqual(len(present_records), 1)
            self.assertEqual(present_records[0].student_id, self.s1_id)
            self.assertEqual(len(absent_records), 2)
            self.assertEqual({r.student_id for r in absent_records}, {self.s2_id, self.s3_id})

    def test_expired_schedule_without_session_is_ignored(self):
        """Lịch đã kết thúc từ hôm qua chưa có ca -> không tạo, không ghi vắng."""
        yesterday_start = datetime(2026, 11, 10, 7, 0, tzinfo=VN_TZ).astimezone(timezone.utc)
        yesterday_end = datetime(2026, 11, 10, 9, 0, tzinfo=VN_TZ).astimezone(timezone.utc)

        with self.factory() as db:
            sched = ClassSchedule(
                class_id=self.class_id,
                title="Lịch cũ hôm qua",
                start_at=yesterday_start,
                end_at=yesterday_end,
            )
            db.add(sched)
            db.commit()

            now = datetime(2026, 11, 11, 10, 0, tzinfo=VN_TZ)
            events = auto_session.tick(db, now)
            self.assertEqual(events, [])
            self.assertIsNone(sched.session_id)
            all_sessions = db.scalars(select(AttendanceSession)).all()
            self.assertEqual(len(all_sessions), 0)

    def test_consecutive_schedules_same_class(self):
        """Hai lịch liền nhau cùng lớp 13-15 và 15-17: tick 15:00 đóng ca trước, mở ca sau."""
        s1_start = datetime(2026, 11, 22, 13, 0, tzinfo=VN_TZ)
        s1_end = datetime(2026, 11, 22, 15, 0, tzinfo=VN_TZ)
        s2_start = datetime(2026, 11, 22, 15, 0, tzinfo=VN_TZ)
        s2_end = datetime(2026, 11, 22, 17, 0, tzinfo=VN_TZ)

        with self.factory() as db:
            sched1 = ClassSchedule(
                class_id=self.class_id,
                title="Buổi 1 (13-15)",
                start_at=s1_start.astimezone(timezone.utc),
                end_at=s1_end.astimezone(timezone.utc),
            )
            sched2 = ClassSchedule(
                class_id=self.class_id,
                title="Buổi 2 (15-17)",
                start_at=s2_start.astimezone(timezone.utc),
                end_at=s2_end.astimezone(timezone.utc),
            )
            db.add_all([sched1, sched2])
            db.commit()

            # Mở ca 1 lúc 13:00
            auto_session.tick(db, s1_start)
            db.refresh(sched1)
            sess1 = db.get(AttendanceSession, sched1.session_id)
            self.assertEqual(sess1.status, "open")

            # SV 1 có mặt ca 1
            att1 = Attendance(
                session_id=sess1.id,
                student_id=self.s1_id,
                checked_at=s1_start.astimezone(timezone.utc),
                status="present",
            )
            db.add(att1)
            db.commit()

            # Tick lúc 15:00 (giao giữa 2 ca)
            events_1500 = auto_session.tick(db, s1_end)
            self.assertEqual(len(events_1500), 2)
            self.assertEqual(events_1500[0], (sess1.id, "closed"))
            sess2_id = events_1500[1][0]
            self.assertEqual(events_1500[1][1], "open")

            db.refresh(sess1)
            self.assertEqual(sess1.status, "closed")

            # Ca 1 có bản ghi absent cho SV 2 và SV 3
            absents_sess1 = db.scalars(select(Attendance).where(Attendance.session_id == sess1.id, Attendance.status == "absent")).all()
            self.assertEqual(len(absents_sess1), 2)

            # Ca 2 đã mở
            sess2 = db.get(AttendanceSession, sess2_id)
            self.assertEqual(sess2.status, "open")

    def test_lifespan_startup_and_shutdown_disabled(self):
        """Khởi động TestClient với AUTO_SESSION_ENABLED=false bật/tắt an toàn không treo."""
        os.environ["AUTO_SESSION_ENABLED"] = "false"
        app = create_app()
        with TestClient(app) as client:
            res = client.get("/health")
            self.assertEqual(res.status_code, 200)

    def test_lifespan_startup_and_shutdown_enabled(self):
        """Khởi động TestClient với AUTO_SESSION_ENABLED=true + interval 5 bật/tắt an toàn không treo."""
        os.environ["AUTO_SESSION_ENABLED"] = "true"
        os.environ["AUTO_SESSION_INTERVAL_SECONDS"] = "5"
        app = create_app()
        with TestClient(app) as client:
            res = client.get("/health")
            self.assertEqual(res.status_code, 200)
