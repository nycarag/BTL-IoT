"""Tests for class schedules API (CRUD, import, export, create-session)."""

import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

os.environ["ADMIN_PASSWORD"] = "test-password-only"
os.environ["DEVICE_TOKEN"] = "test-device-only"
os.environ["FRAME_INTERVAL_SECONDS"] = "0"

from fastapi.testclient import TestClient
import openpyxl
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from starlette.routing import Mount

from app.api import schedules
from app.database import Base, get_db
from app.main import create_app
from app.models.school import AttendanceSession, AuditLog, ClassRoom, ClassSchedule
from app.services import ics


class TestSchedulesAPI(unittest.TestCase):
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

        # Ensure StaticFiles Mount does not shadow API routes
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

        # Seed two classes
        c1 = self.post("/classes", {"code": "D23CTAT01-B", "name": "Lớp An Toàn 1"}).json()
        self.class_id = c1["id"]
        c2 = self.post("/classes", {"code": "D23CTAT02-B", "name": "Lớp An Toàn 2"}).json()
        self.class_id_2 = c2["id"]

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.temp.cleanup()

    def post(self, path: str, data: dict):
        return self.client.post("/api" + path, headers=self.auth, json=data)

    def test_crud_and_conflict_validation(self):
        """Tạo, sửa, xóa lịch; 409 khi trùng giờ bắt đầu và khi chồng giờ; end <= start -> 422."""
        # 1. Tạo lịch hợp lệ
        payload = {
            "class_id": self.class_id,
            "title": "IoT và ứng dụng",
            "date": "2026-11-10",
            "start_time": "07:00",
            "end_time": "09:00",
            "room": "402-A2",
            "note": "Buổi 1",
        }
        res = self.client.post("/api/schedules", headers=self.auth, json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.json()
        schedule_id = data["id"]
        self.assertEqual(data["title"], "IoT và ứng dụng")
        self.assertEqual(data["class_code"], "D23CTAT01-B")
        self.assertEqual(data["start_time"], "07:00")
        self.assertEqual(data["end_time"], "09:00")
        self.assertEqual(data["room"], "402-A2")
        self.assertIsNone(data["session_id"])

        # 2. Trùng giờ bắt đầu -> 409
        dup_payload = {
            "class_id": self.class_id,
            "title": "Môn khác trùng giờ bắt đầu",
            "date": "2026-11-10",
            "start_time": "07:00",
            "end_time": "10:00",
        }
        res_dup = self.client.post("/api/schedules", headers=self.auth, json=dup_payload)
        self.assertEqual(res_dup.status_code, 409)
        self.assertIn("Lớp đã có lịch bắt đầu lúc 07:00", res_dup.json()["detail"])

        # 3. Chồng giờ (08:00 - 10:00 giao với 07:00 - 09:00) -> 409
        overlap_payload = {
            "class_id": self.class_id,
            "title": "Môn khác chồng giờ",
            "date": "2026-11-10",
            "start_time": "08:00",
            "end_time": "10:00",
        }
        res_overlap = self.client.post("/api/schedules", headers=self.auth, json=overlap_payload)
        self.assertEqual(res_overlap.status_code, 409)
        self.assertIn(f"Trùng giờ với lịch #{schedule_id}", res_overlap.json()["detail"])

        # 4. end_time <= start_time -> 422
        bad_time_payload = {
            "class_id": self.class_id,
            "title": "Sai giờ",
            "date": "2026-11-10",
            "start_time": "09:00",
            "end_time": "07:00",
        }
        res_bad_time = self.client.post("/api/schedules", headers=self.auth, json=bad_time_payload)
        self.assertEqual(res_bad_time.status_code, 422)

        equal_time_payload = {
            "class_id": self.class_id,
            "title": "Bằng giờ",
            "date": "2026-11-10",
            "start_time": "09:00",
            "end_time": "09:00",
        }
        res_equal = self.client.post("/api/schedules", headers=self.auth, json=equal_time_payload)
        self.assertEqual(res_equal.status_code, 422)

        # 5. Thời lượng > 6 giờ -> 422
        long_payload = {
            "class_id": self.class_id,
            "title": "Quá 6 tiếng",
            "date": "2026-11-10",
            "start_time": "07:00",
            "end_time": "14:00",
        }
        res_long = self.client.post("/api/schedules", headers=self.auth, json=long_payload)
        self.assertEqual(res_long.status_code, 422)

        # 6. Lớp không tồn tại -> 404
        bad_class_payload = {
            "class_id": 99999,
            "title": "Lớp không có",
            "date": "2026-11-10",
            "start_time": "14:00",
            "end_time": "16:00",
        }
        res_bad_class = self.client.post("/api/schedules", headers=self.auth, json=bad_class_payload)
        self.assertEqual(res_bad_class.status_code, 404)

        # 7. Sửa lịch (PUT)
        update_payload = {
            "class_id": self.class_id,
            "title": "IoT và ứng dụng (Đã sửa)",
            "date": "2026-11-10",
            "start_time": "09:00",
            "end_time": "11:00",
            "room": "501-A2",
            "note": "Phòng mới",
        }
        res_update = self.client.put(f"/api/schedules/{schedule_id}", headers=self.auth, json=update_payload)
        self.assertEqual(res_update.status_code, 200)
        up_data = res_update.json()
        self.assertEqual(up_data["title"], "IoT và ứng dụng (Đã sửa)")
        self.assertEqual(up_data["start_time"], "09:00")
        self.assertEqual(up_data["end_time"], "11:00")
        self.assertEqual(up_data["room"], "501-A2")

        # 8. Xóa lịch (DELETE)
        res_del = self.client.delete(f"/api/schedules/{schedule_id}", headers=self.auth)
        self.assertEqual(res_del.status_code, 204)

        with self.factory() as session:
            check = session.get(ClassSchedule, schedule_id)
            self.assertIsNone(check)

    def test_timezone_storage_and_read(self):
        """Giờ VN 07:00 lưu vào DB là 00:00 UTC, đọc ra API vẫn '07:00'."""
        payload = {
            "class_id": self.class_id,
            "title": "Kiểm tra múi giờ",
            "date": "2026-11-10",
            "start_time": "07:00",
            "end_time": "09:30",
            "room": "301",
        }
        res = self.client.post("/api/schedules", headers=self.auth, json=payload)
        self.assertEqual(res.status_code, 201)
        sched_id = res.json()["id"]

        with self.factory() as session:
            sched = session.get(ClassSchedule, sched_id)
            self.assertIsNotNone(sched)
            # Datetime trong SQLite lưu UTC (naive 00:00:00)
            self.assertEqual(sched.start_at.hour, 0)
            self.assertEqual(sched.start_at.minute, 0)
            self.assertEqual(sched.end_at.hour, 2)
            self.assertEqual(sched.end_at.minute, 30)

        # Đọc lại từ API GET
        res_get = self.client.get(f"/api/schedules?class_id={self.class_id}", headers=self.auth)
        self.assertEqual(res_get.status_code, 200)
        items = res_get.json()
        item = next(it for it in items if it["id"] == sched_id)
        self.assertEqual(item["date"], "2026-11-10")
        self.assertEqual(item["start_time"], "07:00")
        self.assertEqual(item["end_time"], "09:30")

    def test_create_session_and_freeze_behavior(self):
        """create-session tạo buổi draft, gọi lần 2 trả lại đúng buổi cũ; sau khi mở buổi thì sửa/xóa -> 409."""
        payload = {
            "class_id": self.class_id,
            "title": "Lập trình nhúng",
            "date": "2026-11-12",
            "start_time": "13:30",
            "end_time": "15:30",
        }
        res = self.client.post("/api/schedules", headers=self.auth, json=payload)
        sched_id = res.json()["id"]

        # 1. Gọi create-session lần 1 -> 201, tạo AttendanceSession status="draft"
        res_sess1 = self.client.post(f"/api/schedules/{sched_id}/create-session", headers=self.auth)
        self.assertEqual(res_sess1.status_code, 201)
        sess_data1 = res_sess1.json()
        session_id = sess_data1["id"]
        self.assertEqual(sess_data1["status"], "draft")
        self.assertEqual(sess_data1["class_id"], self.class_id)
        self.assertEqual(sess_data1["title"], "Lập trình nhúng · 12/11/2026")

        # 2. Gọi create-session lần 2 -> 200, trả lại đúng buổi cũ
        res_sess2 = self.client.post(f"/api/schedules/{sched_id}/create-session", headers=self.auth)
        self.assertEqual(res_sess2.status_code, 200)
        sess_data2 = res_sess2.json()
        self.assertEqual(sess_data2["id"], session_id)

        # Khi buổi còn draft: xóa lịch thì gỡ liên kết và không lỗi
        # Nhưng trước hết test mở buổi rồi kiểm tra 409
        # Mở buổi điểm danh qua /api/sessions/{session_id}/start
        res_start = self.client.post(f"/api/sessions/{session_id}/start", headers=self.auth)
        self.assertEqual(res_start.status_code, 200)
        self.assertEqual(res_start.json()["status"], "open")

        # Sửa lịch -> 409
        res_edit = self.client.put(
            f"/api/schedules/{sched_id}",
            headers=self.auth,
            json={
                "class_id": self.class_id,
                "title": "Sửa khi buổi đang mở",
                "date": "2026-11-12",
                "start_time": "14:00",
                "end_time": "16:00",
            },
        )
        self.assertEqual(res_edit.status_code, 409)
        self.assertIn("không sửa lịch được", res_edit.json()["detail"])

        # Xóa lịch -> 409
        res_delete = self.client.delete(f"/api/schedules/{sched_id}", headers=self.auth)
        self.assertEqual(res_delete.status_code, 409)
        self.assertIn("không sửa lịch được", res_delete.json()["detail"])

    def test_export_csv_xlsx_ics(self):
        """Export CSV, XLSX, ICS đúng số dòng/sự kiện; ICS parse lại bằng ics.parse_calendar được."""
        # Seed 2 schedules
        self.client.post(
            "/api/schedules",
            headers=self.auth,
            json={
                "class_id": self.class_id,
                "title": "Môn 1",
                "date": "2026-11-10",
                "start_time": "07:00",
                "end_time": "09:00",
                "room": "P101",
                "note": "Ghi chú 1",
            },
        )
        self.client.post(
            "/api/schedules",
            headers=self.auth,
            json={
                "class_id": self.class_id,
                "title": "Môn 2",
                "date": "2026-11-11",
                "start_time": "09:30",
                "end_time": "11:30",
                "room": "P102",
                "note": "Ghi chú 2",
            },
        )

        # 1. Export CSV
        res_csv = self.client.get(
            f"/api/schedules/export?format=csv&class_id={self.class_id}",
            headers=self.auth,
        )
        self.assertEqual(res_csv.status_code, 200)
        self.assertEqual(res_csv.headers["content-type"], "text/csv; charset=utf-8")
        self.assertIn("attachment; filename=lich_hoc_D23CTAT01-B_", res_csv.headers["content-disposition"])
        csv_text = res_csv.content.decode("utf-8-sig")
        lines = [line.strip() for line in csv_text.splitlines() if line.strip()]
        self.assertEqual(len(lines), 3)  # 1 header + 2 rows
        self.assertIn("Mã lớp", lines[0])
        self.assertIn("Tên buổi", lines[0])
        self.assertIn("Môn 1", lines[1])
        self.assertIn("Môn 2", lines[2])

        # 2. Export XLSX
        res_xlsx = self.client.get(
            f"/api/schedules/export?format=xlsx&class_id={self.class_id}",
            headers=self.auth,
        )
        self.assertEqual(res_xlsx.status_code, 200)
        wb = openpyxl.load_workbook(io.BytesIO(res_xlsx.content))
        ws = wb.active
        self.assertEqual(ws.title, "LichHoc")
        rows = list(ws.iter_rows(values_only=True))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0][0], "Mã lớp")
        self.assertEqual(rows[1][1], "Môn 1")
        self.assertEqual(rows[2][1], "Môn 2")
        wb.close()

        # 3. Export ICS & parse back
        res_ics = self.client.get(
            f"/api/schedules/export?format=ics&class_id={self.class_id}",
            headers=self.auth,
        )
        self.assertEqual(res_ics.status_code, 200)
        self.assertEqual(res_ics.headers["content-type"], "text/calendar; charset=utf-8")
        self.assertIn("attachment; filename=lich_hoc_D23CTAT01-B_", res_ics.headers["content-disposition"])

        parsed_events = ics.parse_calendar(res_ics.content)
        self.assertEqual(len(parsed_events), 2)
        self.assertIn("[D23CTAT01-B] Môn 1", parsed_events[0]["title"])
        self.assertIn("[D23CTAT01-B] Môn 2", parsed_events[1]["title"])

        # Check audit log
        with self.factory() as session:
            audit = session.scalar(
                select(AuditLog)
                .where(AuditLog.action == "schedules.export")
                .order_by(AuditLog.id.desc())
            )
            self.assertIsNotNone(audit)
            detail = json.loads(audit.detail)
            self.assertEqual(detail["count"], 2)

    def test_import_template(self):
        """GET /api/schedules/import-template có tiêu đề và 2 dòng ví dụ."""
        res_csv = self.client.get("/api/schedules/import-template?format=csv")
        self.assertEqual(res_csv.status_code, 200)
        lines = [l.strip() for l in res_csv.content.decode("utf-8-sig").splitlines() if l.strip()]
        self.assertEqual(len(lines), 3)  # Header + 2 rows
        self.assertIn("D23CTAT01-B", lines[1])
        self.assertIn("10/11/2026", lines[1])
        self.assertIn("17/11/2026", lines[2])

        res_xlsx = self.client.get("/api/schedules/import-template?format=xlsx")
        self.assertEqual(res_xlsx.status_code, 200)
        wb = openpyxl.load_workbook(io.BytesIO(res_xlsx.content))
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1][0], "D23CTAT01-B")
        wb.close()

        res_bad = self.client.get("/api/schedules/import-template?format=txt")
        self.assertEqual(res_bad.status_code, 422)

    def test_import_csv_preview_and_commit(self):
        """Import CSV preview/commit, có lỗi thì không ghi, '7h30' hiểu đúng."""
        csv_data = (
            "Mã lớp,Tên buổi,Ngày,Bắt đầu,Kết thúc,Phòng,Ghi chú\n"
            "D23CTAT01-B,Toán ứng dụng,15/11/2026,7h30,09:30,301-A2,Buổi 1\n"
            "D23CTAT01-B,Toán ứng dụng,22/11/2026,14h,16h30,301-A2,Buổi 2\n"
        ).encode("utf-8")

        # 1. Preview mode
        res_prev = self.client.post(
            "/api/schedules/import",
            headers=self.auth,
            data={"mode": "preview", "on_conflict": "skip"},
            files={"file": ("schedules.csv", csv_data, "text/csv")},
        )
        self.assertEqual(res_prev.status_code, 200)
        body_prev = res_prev.json()
        self.assertEqual(body_prev["total_rows"], 2)
        self.assertEqual(body_prev["valid_rows"], 2)
        self.assertEqual(body_prev["created"], 2)
        self.assertEqual(len(body_prev["errors"]), 0)
        self.assertEqual(body_prev["rows"][0]["start_time"], "07:30")
        self.assertEqual(body_prev["rows"][1]["start_time"], "14:00")
        self.assertEqual(body_prev["rows"][1]["end_time"], "16:30")

        # Chưa ghi vào DB
        with self.factory() as session:
            count = len(session.scalars(select(ClassSchedule)).all())
            self.assertEqual(count, 0)

        # 2. Commit mode
        res_commit = self.client.post(
            "/api/schedules/import",
            headers=self.auth,
            data={"mode": "commit", "on_conflict": "skip"},
            files={"file": ("schedules.csv", csv_data, "text/csv")},
        )
        self.assertEqual(res_commit.status_code, 200)
        body_commit = res_commit.json()
        self.assertEqual(body_commit["created"], 2)

        with self.factory() as session:
            schedules = session.scalars(select(ClassSchedule).order_by(ClassSchedule.start_at)).all()
            self.assertEqual(len(schedules), 2)
            self.assertEqual(schedules[0].title, "Toán ứng dụng")

        # 3. Import lại với skip -> created=0, skipped=2
        res_skip = self.client.post(
            "/api/schedules/import",
            headers=self.auth,
            data={"mode": "commit", "on_conflict": "skip"},
            files={"file": ("schedules.csv", csv_data, "text/csv")},
        )
        self.assertEqual(res_skip.status_code, 200)
        self.assertEqual(res_skip.json()["created"], 0)
        self.assertEqual(res_skip.json()["skipped"], 2)

        # 4. Import lại với update -> updated=2
        res_update = self.client.post(
            "/api/schedules/import",
            headers=self.auth,
            data={"mode": "commit", "on_conflict": "update"},
            files={"file": ("schedules.csv", csv_data, "text/csv")},
        )
        self.assertEqual(res_update.status_code, 200)
        self.assertEqual(res_update.json()["updated"], 2)

        # 5. Có dòng lỗi + commit -> 422, DB không đổi
        bad_csv = (
            "Mã lớp,Tên buổi,Ngày,Bắt đầu,Kết thúc,Phòng,Ghi chú\n"
            "D23CTAT01-B,Toán lỗi,31/02/2026,07:00,09:00,301,Lỗi ngày\n"
            "D23CTAT01-B,Toán mới,29/11/2026,07:00,09:00,301,Hợp lệ\n"
        ).encode("utf-8")
        res_err = self.client.post(
            "/api/schedules/import",
            headers=self.auth,
            data={"mode": "commit"},
            files={"file": ("bad.csv", bad_csv, "text/csv")},
        )
        self.assertEqual(res_err.status_code, 422)
        with self.factory() as session:
            # Vẫn chỉ có 2 lịch cũ
            self.assertEqual(len(session.scalars(select(ClassSchedule)).all()), 2)

    def test_import_ics_and_cross_class(self):
        """Import .ics thiếu class_id -> 422; xuất ics rồi nhập lại ics vào lớp khác ra đủ số buổi."""
        # Seed 2 schedules for class 1
        self.client.post(
            "/api/schedules",
            headers=self.auth,
            json={
                "class_id": self.class_id,
                "title": "Mạng máy tính",
                "date": "2026-11-15",
                "start_time": "07:00",
                "end_time": "09:00",
                "room": "P201",
            },
        )
        self.client.post(
            "/api/schedules",
            headers=self.auth,
            json={
                "class_id": self.class_id,
                "title": "Hệ điều hành",
                "date": "2026-11-16",
                "start_time": "09:00",
                "end_time": "11:00",
                "room": "P202",
            },
        )

        # Xuất ICS của class 1
        res_export = self.client.get(
            f"/api/schedules/export?format=ics&class_id={self.class_id}",
            headers=self.auth,
        )
        self.assertEqual(res_export.status_code, 200)
        ics_bytes = res_export.content

        # 1. Import ICS thiếu class_id -> 422 "Tệp .ics cần chọn lớp"
        res_no_class = self.client.post(
            "/api/schedules/import",
            headers=self.auth,
            files={"file": ("calendar.ics", ics_bytes, "text/calendar")},
        )
        self.assertEqual(res_no_class.status_code, 422)
        self.assertIn("Tệp .ics cần chọn lớp", res_no_class.json()["detail"])

        # 2. Nhập ICS vào lớp khác (class_id_2) với class_id được chọn
        res_cross = self.client.post(
            "/api/schedules/import",
            headers=self.auth,
            data={"mode": "commit", "class_id": self.class_id_2},
            files={"file": ("calendar.ics", ics_bytes, "text/calendar")},
        )
        self.assertEqual(res_cross.status_code, 200)
        body = res_cross.json()
        self.assertEqual(body["created"], 2)

        with self.factory() as session:
            schedules_c2 = session.scalars(
                select(ClassSchedule).where(ClassSchedule.class_id == self.class_id_2)
            ).all()
            self.assertEqual(len(schedules_c2), 2)
            titles = [s.title for s in schedules_c2]
            self.assertIn("Mạng máy tính", titles)
            self.assertIn("Hệ điều hành", titles)

    def test_filter_date_range(self):
        """Lọc date_from và date_to chính xác theo giờ VN."""
        dates = ["2026-11-01", "2026-11-05", "2026-11-10", "2026-11-20"]
        for d in dates:
            self.client.post(
                "/api/schedules",
                headers=self.auth,
                json={
                    "class_id": self.class_id,
                    "title": f"Buổi ngày {d}",
                    "date": d,
                    "start_time": "08:00",
                    "end_time": "10:00",
                },
            )

        # Lọc từ 05 đến 10 -> bao gồm cả 05 và 10
        res = self.client.get(
            f"/api/schedules?class_id={self.class_id}&date_from=2026-11-05&date_to=2026-11-10",
            headers=self.auth,
        )
        self.assertEqual(res.status_code, 200)
        items = res.json()
        self.assertEqual(len(items), 2)
        self.assertEqual({it["date"] for it in items}, {"2026-11-05", "2026-11-10"})

        # Lọc date_from=2026-11-15 -> chỉ có 20
        res_after = self.client.get(
            f"/api/schedules?class_id={self.class_id}&date_from=2026-11-15",
            headers=self.auth,
        )
        self.assertEqual(len(res_after.json()), 1)
        self.assertEqual(res_after.json()[0]["date"], "2026-11-20")

    def test_unauthenticated(self):
        """Không có token -> 401."""
        res_get = self.client.get("/api/schedules")
        self.assertEqual(res_get.status_code, 401)

        res_post = self.client.post("/api/schedules", json={})
        self.assertEqual(res_post.status_code, 401)

        res_export = self.client.get("/api/schedules/export?format=csv")
        self.assertEqual(res_export.status_code, 401)

        res_import = self.client.post("/api/schedules/import")
        self.assertEqual(res_import.status_code, 401)


if __name__ == "__main__":
    unittest.main()
