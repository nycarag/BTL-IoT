"""Tests for schedule import keyword filter (Task K02)."""

import io
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

from app.api import schedules
from app.database import Base, get_db
from app.main import create_app
from app.models.school import AuditLog, ClassRoom, ClassSchedule

VN_TZ = timezone(timedelta(hours=7), "ICT")

PTIT_ICS_SAMPLE = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "PRODID:-//PTIT//QLDT//VI\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:event-1@ptit\r\n"
    "DTSTART;VALUE=DATE-TIME:20260810T130000\r\n"
    "DTEND;VALUE=DATE-TIME:20260810T150000\r\n"
    "SUMMARY;LANGUAGE=en-us:IoT và ứng dụng (CT02)\r\n"
    "DESCRIPTION:CT02 - INT14149\r\n"
    "LOCATION:301-NT-301 - CS Ngọc Trục\r\n"
    "END:VEVENT\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:event-2@ptit\r\n"
    "DTSTART;VALUE=DATE-TIME:20260811T070000\r\n"
    "DTEND;VALUE=DATE-TIME:20260811T090000\r\n"
    "SUMMARY;LANGUAGE=en-us:Kỹ thuật lập trình\r\n"
    "DESCRIPTION:CT01 - INT1306\r\n"
    "LOCATION:101-A2 - CS Trần Phú\r\n"
    "END:VEVENT\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:event-3@ptit\r\n"
    "DTSTART;VALUE=DATE-TIME:20260812T090000\r\n"
    "DTEND;VALUE=DATE-TIME:20260812T110000\r\n"
    "SUMMARY;LANGUAGE=en-us:Toán rời rạc\r\n"
    "DESCRIPTION:CT03 - INT1155\r\n"
    "LOCATION:202-A3 - CS Trần Phú\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)


class TestScheduleKeywordFilter(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{self.temp.name}/test.db",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(self.engine, expire_on_commit=False)

        app = create_app()
        app.include_router(schedules.router, prefix="/api")

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

        res_class = self.client.post(
            "/api/classes",
            headers=self.auth,
            json={"code": "D23CTAT02-B", "name": "Lớp IoT Thử Nghiệm"},
        ).json()
        self.class_id = res_class["id"]

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.temp.cleanup()

    def test_preview_with_lowercase_keyword(self):
        """Keyword 'iot' khớp casefold với tiêu đề môn 'IoT và ứng dụng (CT02)', lọc bỏ 2 môn khác."""
        files = {"file": ("lich_ptit.ics", io.BytesIO(PTIT_ICS_SAMPLE.encode("utf-8")), "text/calendar")}
        data = {
            "mode": "preview",
            "class_id": str(self.class_id),
            "keyword": "iot",
        }
        res = self.client.post("/api/schedules/import", headers=self.auth, files=files, data=data)
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["total_rows"], 3)
        self.assertEqual(body["valid_rows"], 1)
        self.assertEqual(body["filtered_out"], 2)
        self.assertEqual(len(body["rows"]), 1)
        self.assertIn("IoT", body["rows"][0]["title"])

    def test_preview_with_subject_code_keyword(self):
        """Keyword 'INT14149' khớp mã môn trong note/description, lọc bỏ 2 môn khác."""
        files = {"file": ("lich_ptit.ics", io.BytesIO(PTIT_ICS_SAMPLE.encode("utf-8")), "text/calendar")}
        data = {
            "mode": "preview",
            "class_id": str(self.class_id),
            "keyword": "INT14149",
        }
        res = self.client.post("/api/schedules/import", headers=self.auth, files=files, data=data)
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["total_rows"], 3)
        self.assertEqual(body["valid_rows"], 1)
        self.assertEqual(body["filtered_out"], 2)
        self.assertEqual(len(body["rows"]), 1)

    def test_preview_without_keyword(self):
        """Không có keyword -> trả về đủ 3 dòng như trước, filtered_out = 0."""
        files = {"file": ("lich_ptit.ics", io.BytesIO(PTIT_ICS_SAMPLE.encode("utf-8")), "text/calendar")}
        data = {
            "mode": "preview",
            "class_id": str(self.class_id),
        }
        res = self.client.post("/api/schedules/import", headers=self.auth, files=files, data=data)
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["total_rows"], 3)
        self.assertEqual(body["valid_rows"], 3)
        self.assertEqual(body["filtered_out"], 0)
        self.assertEqual(len(body["rows"]), 3)

    def test_commit_with_keyword(self):
        """Commit với keyword chỉ ghi 1 lịch vào DB, bắt đầu đúng 13:00 giờ VN, ghi log đầy đủ."""
        files = {"file": ("lich_ptit.ics", io.BytesIO(PTIT_ICS_SAMPLE.encode("utf-8")), "text/calendar")}
        data = {
            "mode": "commit",
            "class_id": str(self.class_id),
            "keyword": "INT14149",
        }
        res = self.client.post("/api/schedules/import", headers=self.auth, files=files, data=data)
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["created"], 1)
        self.assertEqual(body["filtered_out"], 2)

        with self.factory() as session:
            scheds = session.scalars(select(ClassSchedule).where(ClassSchedule.class_id == self.class_id)).all()
            self.assertEqual(len(scheds), 1)
            sched = scheds[0]
            start_utc = sched.start_at.replace(tzinfo=timezone.utc) if sched.start_at.tzinfo is None else sched.start_at
            start_vn = start_utc.astimezone(VN_TZ)
            self.assertEqual(start_vn.hour, 13)
            self.assertEqual(start_vn.minute, 0)
            self.assertEqual(start_vn.strftime("%Y-%m-%d"), "2026-08-10")

            # Kiểm tra audit log
            logs = session.scalars(select(AuditLog).where(AuditLog.action == "schedules.import")).all()
            self.assertEqual(len(logs), 1)
            log = logs[0]
            detail = json.loads(log.detail) if isinstance(log.detail, str) else log.detail
            self.assertEqual(detail.get("keyword"), "INT14149")
            self.assertEqual(detail.get("filtered_out"), 2)
            self.assertEqual(detail.get("created"), 1)

    def test_keyword_too_long(self):
        """Từ khóa dài quá 100 ký tự -> HTTP 422 tiếng Việt."""
        files = {"file": ("lich_ptit.ics", io.BytesIO(PTIT_ICS_SAMPLE.encode("utf-8")), "text/calendar")}
        data = {
            "mode": "preview",
            "class_id": str(self.class_id),
            "keyword": "X" * 101,
        }
        res = self.client.post("/api/schedules/import", headers=self.auth, files=files, data=data)
        self.assertEqual(res.status_code, 422)
        self.assertIn("100", res.text)

    def test_csv_keyword_filter(self):
        """Lọc từ khóa hoạt động đúng với tệp CSV."""
        csv_content = (
            "Mã lớp,Tên buổi,Ngày,Bắt đầu,Kết thúc,Phòng,Ghi chú\n"
            "D23CTAT02-B,IoT Buổi 1,15/11/2026,07:00,09:00,402-A2,Môn IoT\n"
            "D23CTAT02-B,An toàn mạng,16/11/2026,07:00,09:00,403-A2,Môn ATTT\n"
        )
        files = {"file": ("schedules.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
        data = {
            "mode": "preview",
            "keyword": "ATTT",
        }
        res = self.client.post("/api/schedules/import", headers=self.auth, files=files, data=data)
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["total_rows"], 2)
        self.assertEqual(body["valid_rows"], 1)
        self.assertEqual(body["filtered_out"], 1)
        self.assertEqual(body["rows"][0]["title"], "An toàn mạng")
