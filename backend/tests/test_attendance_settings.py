"""Tests for configurable late threshold API and attendance recomputation (Task K04)."""

import json
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
from starlette.routing import Mount

from app.api import attendance, sessions, settings as settings_api
from app.database import Base, get_db
from app.main import create_app
from app.models.school import Attendance, AttendanceSession, AuditLog, ClassRoom, ClassSchedule, Student


class TestAttendanceSettings(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{self.temp.name}/test.db",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(self.engine, expire_on_commit=False)

        app = create_app()
        app.include_router(settings_api.router, prefix="/api")
        app.include_router(sessions.router, prefix="/api")
        app.include_router(attendance.router, prefix="/api")

        mounts = [r for r in app.routes if isinstance(r, Mount)]
        for m in mounts:
            app.routes.remove(m)
            app.routes.append(m)

        def db():
            with self.factory() as session:
                yield session

        app.dependency_overrides[get_db] = db
        self.client = TestClient(app)

        token = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "test-password-only"},
        ).json()["access_token"]
        self.auth = {"Authorization": f"Bearer {token}"}

        # Seed 1 lớp và 2 sinh viên
        with self.factory() as session:
            c = ClassRoom(code="D23CTAT01-B", name="Lớp An Toàn")
            session.add(c)
            session.flush()

            s1 = Student(student_code="B23DCAT001", name="SV A", class_id=c.id)
            s2 = Student(student_code="B23DCAT002", name="SV B", class_id=c.id)
            session.add_all([s1, s2])
            session.commit()

            self.class_id = c.id
            self.s1_id = s1.id
            self.s2_id = s2.id

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.temp.cleanup()

    def test_get_settings_default_and_unauthenticated(self):
        """GET /settings/attendance mặc định 15, chưa đăng nhập trả về 401."""
        # Chưa đăng nhập -> 401
        res_no_auth = self.client.get("/api/settings/attendance")
        self.assertEqual(res_no_auth.status_code, 401)

        # Đã đăng nhập -> 200, 15 phút
        res = self.client.get("/api/settings/attendance", headers=self.auth)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"late_after_minutes": 15})

    def test_put_settings_validation_and_audit(self):
        """PUT 0 hoặc 121 trả về 422 tiếng Việt; PUT hợp lệ ghi nhận audit log."""
        # 0 -> 422
        res_0 = self.client.put("/api/settings/attendance", headers=self.auth, json={"late_after_minutes": 0})
        self.assertEqual(res_0.status_code, 422)

        # 121 -> 422
        res_121 = self.client.put("/api/settings/attendance", headers=self.auth, json={"late_after_minutes": 121})
        self.assertEqual(res_121.status_code, 422)

        # 20 -> 200
        res_20 = self.client.put("/api/settings/attendance", headers=self.auth, json={"late_after_minutes": 20})
        self.assertEqual(res_20.status_code, 200)
        body = res_20.json()
        self.assertEqual(body["late_after_minutes"], 20)

        # GET lại thấy 20
        res_get = self.client.get("/api/settings/attendance", headers=self.auth)
        self.assertEqual(res_get.json()["late_after_minutes"], 20)

        # GET /api/system/status cũng trả về 20
        res_sys = self.client.get("/api/system/status", headers=self.auth)
        self.assertEqual(res_sys.status_code, 200)
        self.assertEqual(res_sys.json()["late_after_minutes"], 20)

        # Kiểm tra AuditLog
        with self.factory() as session:
            logs = session.scalars(select(AuditLog).where(AuditLog.action == "settings.update")).all()
            self.assertEqual(len(logs), 1)
            detail = json.loads(logs[0].detail) if isinstance(logs[0].detail, str) else logs[0].detail
            self.assertEqual(detail["old"], 15)
            self.assertEqual(detail["new"], 20)

    def test_recomputation_of_schedules_attendance(self):
        """Có lịch 13:00, bản ghi 13:17 là late với 15 -> PUT 20 thành present -> PUT 10 lại late; absent không đổi."""
        start_13h = datetime(2026, 11, 15, 6, 0, tzinfo=timezone.utc)  # 13:00 giờ VN
        checkin_13h17 = start_13h + timedelta(minutes=17)

        with self.factory() as session:
            sess = AttendanceSession(class_id=self.class_id, title="Buổi Chiều", status="open", starts_at=start_13h)
            session.add(sess)
            session.flush()

            sched = ClassSchedule(
                class_id=self.class_id,
                title="Lịch Chiều",
                start_at=start_13h,
                end_at=start_13h + timedelta(hours=2),
                session_id=sess.id,
            )
            session.add(sched)
            session.flush()

            # SV 1 checkin 13:17 (với ngưỡng 15 là late)
            att1 = Attendance(
                session_id=sess.id,
                student_id=self.s1_id,
                checked_at=checkin_13h17,
                status="late",
                verification="face+pad",
            )
            # SV 2 là absent
            att2 = Attendance(
                session_id=sess.id,
                student_id=self.s2_id,
                checked_at=start_13h + timedelta(hours=2),
                status="absent",
                verification="auto-absent",
            )
            session.add_all([att1, att2])
            session.commit()
            sess_id = sess.id
            att1_id = att1.id
            att2_id = att2.id

        # 1. Ban đầu ngưỡng 15, att1 là late
        res_put_20 = self.client.put("/api/settings/attendance", headers=self.auth, json={"late_after_minutes": 20})
        self.assertEqual(res_put_20.status_code, 200)
        self.assertEqual(res_put_20.json()["recomputed"], 1)

        with self.factory() as session:
            a1 = session.get(Attendance, att1_id)
            a2 = session.get(Attendance, att2_id)
            self.assertEqual(a1.status, "present")
            self.assertEqual(a2.status, "absent")  # absent không đổi

        # 2. Đổi ngưỡng về 10 -> att1 đổi lại thành late
        res_put_10 = self.client.put("/api/settings/attendance", headers=self.auth, json={"late_after_minutes": 10})
        self.assertEqual(res_put_10.status_code, 200)
        self.assertEqual(res_put_10.json()["recomputed"], 1)

        with self.factory() as session:
            a1 = session.get(Attendance, att1_id)
            a2 = session.get(Attendance, att2_id)
            self.assertEqual(a1.status, "late")
            self.assertEqual(a2.status, "absent")
