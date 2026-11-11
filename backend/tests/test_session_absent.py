"""Tests for session close auto-absent generation (Task K03)."""

import os
import tempfile
import unittest

os.environ["ADMIN_PASSWORD"] = "test-password-only"
os.environ["DEVICE_TOKEN"] = "test-device-only"
os.environ["FRAME_INTERVAL_SECONDS"] = "0"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from starlette.routing import Mount

from app.api import attendance, sessions
from app.database import Base, get_db
from app.main import create_app
from app.models.school import Attendance, AttendanceSession, ClassRoom, Student


class TestSessionAbsent(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{self.temp.name}/test.db",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(self.engine, expire_on_commit=False)

        app = create_app()
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

        # Tạo lớp 1 có 3 sinh viên, lớp 2 có 1 sinh viên
        with self.factory() as session:
            c1 = ClassRoom(code="D23CTAT01-B", name="Lớp 1")
            c2 = ClassRoom(code="D23CTAT02-B", name="Lớp 2")
            session.add_all([c1, c2])
            session.flush()

            s1 = Student(student_code="B23DCAT001", name="Nguyễn Văn A", class_id=c1.id)
            s2 = Student(student_code="B23DCAT002", name="Trần Thị B", class_id=c1.id)
            s3 = Student(student_code="B23DCAT003", name="Lê Văn C", class_id=c1.id)
            s_other = Student(student_code="B23DCAT999", name="SV Lớp Khác", class_id=c2.id)
            session.add_all([s1, s2, s3, s_other])
            session.commit()

            self.class_id = c1.id
            self.class_other_id = c2.id
            self.s1_id = s1.id
            self.s2_id = s2.id
            self.s3_id = s3.id
            self.s_other_id = s_other.id

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.temp.cleanup()

    def test_close_session_generates_auto_absent(self):
        """Đóng ca tạo bản ghi vắng mặt (auto-absent) cho sinh viên chưa điểm danh; không đụng lớp khác."""
        # 1. Tạo và mở ca
        res_create = self.client.post("/api/sessions", headers=self.auth, json={"class_id": self.class_id, "title": "Buổi 1"})
        self.assertEqual(res_create.status_code, 201)
        sess_id = res_create.json()["id"]

        res_start = self.client.post(f"/api/sessions/{sess_id}/start", headers=self.auth)
        self.assertEqual(res_start.status_code, 200)

        # 2. SV 1 điểm danh thủ công qua API
        res_att = self.client.post(
            f"/api/sessions/{sess_id}/manual-attendance",
            headers=self.auth,
            json={"student_id": self.s1_id, "reason": "Xác minh trực tiếp"},
        )
        self.assertEqual(res_att.status_code, 200)

        # 3. Đóng ca qua POST /api/sessions/{id}/close
        res_close = self.client.post(f"/api/sessions/{sess_id}/close", headers=self.auth)
        self.assertEqual(res_close.status_code, 200)

        # 4. Kiểm tra danh sách điểm danh của ca
        res_list = self.client.get(f"/api/attendance?session_id={sess_id}", headers=self.auth)
        self.assertEqual(res_list.status_code, 200)
        records = res_list.json()

        # Có đúng 3 bản ghi (1 có mặt/muộn + 2 vắng mặt)
        self.assertEqual(len(records), 3)

        present_records = [r for r in records if r["status"] in ("present", "late")]
        absent_records = [r for r in records if r["status"] == "absent"]

        self.assertEqual(len(present_records), 1)
        self.assertEqual(present_records[0]["student_id"], self.s1_id)

        self.assertEqual(len(absent_records), 2)
        absent_sids = {r["student_id"] for r in absent_records}
        self.assertEqual(absent_sids, {self.s2_id, self.s3_id})

        for r in absent_records:
            self.assertEqual(r["verification"], "auto-absent")
            self.assertIsNone(r["device_id"])

        # Sinh viên lớp khác (s_other_id) tuyệt đối không có bản ghi trong ca này
        self.assertNotIn(self.s_other_id, {r["student_id"] for r in records})

        # 5. Đóng lần 2 -> 409 "Only an open session can be closed"
        res_close_again = self.client.post(f"/api/sessions/{sess_id}/close", headers=self.auth)
        self.assertEqual(res_close_again.status_code, 409)
        self.assertEqual(res_close_again.json()["detail"], "Only an open session can be closed")

        # 6. Mở lại ca đã đóng -> 409 "Closed session cannot be reopened"
        res_reopen = self.client.post(f"/api/sessions/{sess_id}/start", headers=self.auth)
        self.assertEqual(res_reopen.status_code, 409)
        self.assertEqual(res_reopen.json()["detail"], "Closed session cannot be reopened")

    def test_open_new_session_closes_previous_open_session_with_absent(self):
        """Mở ca mới cùng lớp khi ca cũ đang open -> ca cũ tự đóng và có bản ghi vắng."""
        # Tạo và mở ca 1
        s1 = self.client.post("/api/sessions", headers=self.auth, json={"class_id": self.class_id, "title": "Ca 1"}).json()
        self.client.post(f"/api/sessions/{s1['id']}/start", headers=self.auth)

        # Tạo và mở ca 2 cùng lớp
        s2 = self.client.post("/api/sessions", headers=self.auth, json={"class_id": self.class_id, "title": "Ca 2"}).json()
        res_start_2 = self.client.post(f"/api/sessions/{s2['id']}/start", headers=self.auth)
        self.assertEqual(res_start_2.status_code, 200)

        # Kiểm tra ca 1 đã bị closed và có đủ 3 bản ghi absent
        with self.factory() as session:
            db_s1 = session.get(AttendanceSession, s1["id"])
            self.assertEqual(db_s1.status, "closed")

            atts1 = session.scalars(select(Attendance).where(Attendance.session_id == s1["id"])).all()
            self.assertEqual(len(atts1), 3)
            for a in atts1:
                self.assertEqual(a.status, "absent")
                self.assertEqual(a.verification, "auto-absent")
