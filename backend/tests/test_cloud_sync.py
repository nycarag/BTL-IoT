"""Tests for Gateway -> Cloud synchronization module (Task C01)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import http.server
import json
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.school import AppSetting, Attendance, AttendanceSession, ClassRoom, Device, Student
from app.services import cloud_sync

VN_TZ = timezone(timedelta(hours=7))


class MockCloudServer:
    def __init__(self):
        self.received_posts: list[dict] = []
        self.response_error: str | None = None
        self.status_code: int = 200

        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length > 0 else b""
                parsed = json.loads(body.decode("utf-8")) if body else {}
                outer.received_posts.append(parsed)

                if self.path == "/exec-302":
                    self.send_response(302)
                    self.send_header("Location", "/ket-qua")
                    self.end_headers()
                    return

                self.send_response(outer.status_code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                if outer.response_error:
                    self.wfile.write(json.dumps({"ok": False, "error": outer.response_error}).encode("utf-8"))
                else:
                    added_count = len(parsed.get("attendance", []))
                    self.wfile.write(json.dumps({
                        "ok": True,
                        "added": added_count,
                        "commands": [{"id": 1, "device_id": "esp32-cam-01", "lenh": "flash", "gia_tri": ""}],
                    }).encode("utf-8"))

            def do_GET(self):
                if self.path == "/ket-qua":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": True, "added": 1, "commands": []}).encode("utf-8"))
                    return
                self.send_response(404)
                self.end_headers()

            def log_message(self, format, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}/exec"

    def shutdown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2.0)


class TestCloudSync(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{self.temp.name}/test.db",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(self.engine, expire_on_commit=False)

        # Patch SessionLocal trong cloud_sync
        self.session_patcher = patch("app.services.cloud_sync.SessionLocal", self.factory)
        self.session_patcher.start()

        # Reset module state
        with cloud_sync._lock:
            cloud_sync._state.update({
                "last_ok_at": None,
                "last_error": None,
                "sent_total": 0,
                "cursor": 0,
                "pending": 0,
            })

        self.mock_cloud = MockCloudServer()

        # Khởi tạo dữ liệu mẫu cơ bản
        with self.factory() as db:
            self.classroom = ClassRoom(code="D23CTAT01-B", name="Lớp An Toàn 1")
            db.add(self.classroom)
            db.flush()

            self.student1 = Student(student_code="B23DCAT001", name="Nguyễn Văn A", class_id=self.classroom.id)
            self.student2 = Student(student_code="B23DCAT002", name="Trần Thị B", class_id=self.classroom.id)
            db.add_all([self.student1, self.student2])
            db.flush()

            self.session = AttendanceSession(class_id=self.classroom.id, title="Buổi 1 IoT", status="open")
            db.add(self.session)
            db.flush()

            self.device = Device(id="esp32-cam-01", name="ESP32 Cửa Lớp", ip_address="192.168.1.100")
            db.add(self.device)
            db.commit()

            self.class_id = self.classroom.id
            self.session_id = self.session.id
            self.student1_id = self.student1.id
            self.student2_id = self.student2.id

    def tearDown(self):
        self.mock_cloud.shutdown()
        self.session_patcher.stop()
        self.engine.dispose()
        self.temp.cleanup()

    def test_collect_attendance_contract_and_timezone(self):
        """collect_attendance: đúng đủ khóa, event_id có tiền tố gateway, giờ đổi sang VN (+7), device_id None ra '', không có khóa ngoài hợp đồng trừ _id."""
        with self.factory() as db:
            # Datetime naive UTC: 2026-11-12 02:30:00 -> VN (+7): 2026-11-12 09:30:00
            naive_utc = datetime(2026, 11, 12, 2, 30, 0)
            att = Attendance(
                session_id=self.session_id,
                student_id=self.student1_id,
                checked_at=naive_utc,
                status="present",
                device_id=None,
                verification="face+pad",
            )
            db.add(att)
            db.commit()

            results = cloud_sync.collect_attendance(db, after_id=0, gateway_id="gw-01", limit=10)
            self.assertEqual(len(results), 1)
            row = results[0]

            expected_keys = {
                "event_id", "checked_at", "student_code", "student_name", "class_code",
                "session_id", "session_title", "status", "device_id", "verification", "_id",
            }
            self.assertEqual(set(row.keys()), expected_keys)
            self.assertEqual(row["event_id"], f"gw-01-att-{att.id}")
            self.assertEqual(row["checked_at"], "2026-11-12 09:30:00")
            self.assertEqual(row["student_code"], "B23DCAT001")
            self.assertEqual(row["student_name"], "Nguyễn Văn A")
            self.assertEqual(row["class_code"], "D23CTAT01-B")
            self.assertEqual(row["session_id"], self.session_id)
            self.assertEqual(row["session_title"], "Buổi 1 IoT")
            self.assertEqual(row["status"], "present")
            self.assertEqual(row["device_id"], "")
            self.assertEqual(row["verification"], "face+pad")
            self.assertEqual(row["_id"], att.id)

    def test_sync_once_success_and_cursor_progression(self):
        """sync_once thành công: cloud giả nhận đúng 1 POST có token, gateway_id, attendance, devices, command_results; con trỏ tăng; gọi lần hai không gửi lại bản ghi cũ."""
        with self.factory() as db:
            att1 = Attendance(session_id=self.session_id, student_id=self.student1_id, status="present", device_id="esp32-cam-01")
            att2 = Attendance(session_id=self.session_id, student_id=self.student2_id, status="late", device_id="esp32-cam-01")
            db.add_all([att1, att2])
            db.commit()

        # Gọi lần 1
        res1 = cloud_sync.sync_once(url=self.mock_cloud.url, token="test-token-123", backfill=True)
        self.assertTrue(res1["ok"])
        self.assertEqual(res1["sent"], 2)
        self.assertEqual(res1["added"], 2)
        self.assertEqual(res1["pending"], 0)
        self.assertEqual(len(self.mock_cloud.received_posts), 1)

        post = self.mock_cloud.received_posts[0]
        self.assertEqual(post["token"], "test-token-123")
        self.assertEqual(post["gateway_id"], "gateway-laptop-01")
        self.assertIn("attendance", post)
        self.assertIn("devices", post)
        self.assertIn("command_results", post)
        self.assertEqual(len(post["attendance"]), 2)
        # Khóa _id phải được loại bỏ trước khi gửi lên Cloud
        for row in post["attendance"]:
            self.assertNotIn("_id", row)

        # Kiểm tra con trỏ đã được lưu vào AppSetting
        with self.factory() as db:
            setting = db.get(AppSetting, "cloud_last_attendance_id")
            self.assertIsNotNone(setting)
            self.assertEqual(int(setting.value), 2)

        # Gọi lần 2: không gửi lại bản ghi cũ
        res2 = cloud_sync.sync_once(url=self.mock_cloud.url, token="test-token-123", backfill=True)
        self.assertTrue(res2["ok"])
        self.assertEqual(res2["sent"], 0)
        self.assertEqual(len(self.mock_cloud.received_posts), 2)
        self.assertEqual(len(self.mock_cloud.received_posts[1]["attendance"]), 0)

    def test_network_drop_and_recover(self):
        """Mất mạng (cổng không ai nghe) rồi có lại: lần đầu ok=False, con trỏ giữ nguyên, pending > 0; lần sau gửi đủ các bản ghi đã tồn."""
        with self.factory() as db:
            att = Attendance(session_id=self.session_id, student_id=self.student1_id, status="present")
            db.add(att)
            db.commit()

        # Tìm một cổng rảnh không có ai lắng nghe
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            free_port = s.getsockname()[1]

        dead_url = f"http://127.0.0.1:{free_port}/exec"
        res_fail = cloud_sync.sync_once(url=dead_url, token="token", backfill=True)
        self.assertFalse(res_fail["ok"])
        self.assertGreater(res_fail["pending"], 0)

        # Con trỏ vẫn chưa được cập nhật trong DB
        with self.factory() as db:
            setting = db.get(AppSetting, "cloud_last_attendance_id")
            self.assertIsNone(setting)

        # Có mạng trở lại: gọi vào mock_cloud
        res_ok = cloud_sync.sync_once(url=self.mock_cloud.url, token="token", backfill=True)
        self.assertTrue(res_ok["ok"])
        self.assertEqual(res_ok["sent"], 1)
        self.assertEqual(res_ok["pending"], 0)

    def test_cloud_error_token_response(self):
        """Cloud trả {'ok': false, 'error': 'token'}: con trỏ giữ nguyên, last_error có chữ 'token' nhưng không chứa giá trị token."""
        with self.factory() as db:
            att = Attendance(session_id=self.session_id, student_id=self.student1_id, status="present")
            db.add(att)
            db.commit()

        secret_token = "my-super-secret-token-xyz-987"
        self.mock_cloud.response_error = "token"

        res = cloud_sync.sync_once(url=self.mock_cloud.url, token=secret_token, backfill=True)
        self.assertFalse(res["ok"])

        # Con trỏ giữ nguyên
        with self.factory() as db:
            setting = db.get(AppSetting, "cloud_last_attendance_id")
            self.assertIsNone(setting)

        st = cloud_sync.status()
        self.assertIn("token", str(st["last_error"]).lower())
        self.assertNotIn(secret_token, str(st["last_error"]))

    def test_empty_url_disabled(self):
        """URL trống: {'enabled': False}, cloud giả không nhận request nào."""
        res = cloud_sync.sync_once(url="", token="token")
        self.assertEqual(res, {"enabled": False})
        self.assertEqual(len(self.mock_cloud.received_posts), 0)

    def test_post_json_follows_302_redirect(self):
        """post_json đi theo 302: POST /exec trả 302 Location /ket-qua, GET /ket-qua trả JSON; hàm trả đúng JSON đó."""
        redirect_url = f"http://127.0.0.1:{self.mock_cloud.port}/exec-302"
        data = cloud_sync.post_json(redirect_url, {"sample": "payload"})
        self.assertEqual(data, {"ok": True, "added": 1, "commands": []})

    def test_status_does_not_leak_url_or_token(self):
        """status() không chứa URL, không chứa token."""
        st = cloud_sync.status()
        self.assertNotIn("url", st)
        self.assertNotIn("token", st)
        self.assertNotIn("cloud_sync_url", st)
        self.assertNotIn("cloud_sync_token", st)
        for key, val in st.items():
            if val is not None:
                self.assertNotIn("token", key)
                self.assertNotIn("url", key)

    def test_absent_record_sent(self):
        """Bản ghi 'absent' (do đóng ca sinh ra, device_id None) cũng được gửi với device_id rỗng."""
        with self.factory() as db:
            att = Attendance(
                session_id=self.session_id,
                student_id=self.student1_id,
                status="absent",
                device_id=None,
                verification="absent",
            )
            db.add(att)
            db.commit()

        res = cloud_sync.sync_once(url=self.mock_cloud.url, token="token", backfill=True)
        self.assertTrue(res["ok"])
        self.assertEqual(res["sent"], 1)

        post = self.mock_cloud.received_posts[0]
        self.assertEqual(len(post["attendance"]), 1)
        sent_att = post["attendance"][0]
        self.assertEqual(sent_att["status"], "absent")
        self.assertEqual(sent_att["device_id"], "")
        self.assertEqual(sent_att["verification"], "absent")

    def test_backfill_false_behavior(self):
        """backfill=False: bản ghi có trước lần đồng bộ đầu không bị gửi, bản ghi tạo sau đó thì được gửi."""
        # 1. Tạo 2 bản ghi cũ trước lần đồng bộ đầu tiên
        with self.factory() as db:
            att1 = Attendance(session_id=self.session_id, student_id=self.student1_id, status="present")
            att2 = Attendance(session_id=self.session_id, student_id=self.student2_id, status="late")
            db.add_all([att1, att2])
            db.commit()

        # 2. Lần đồng bộ đầu tiên với backfill=False: không gửi dữ liệu cũ
        res1 = cloud_sync.sync_once(url=self.mock_cloud.url, token="token", backfill=False)
        self.assertTrue(res1["ok"])
        self.assertEqual(res1["sent"], 0)
        self.assertEqual(len(self.mock_cloud.received_posts[0]["attendance"]), 0)

        # Con trỏ trong DB được chốt ở Attendance.id lớn nhất hiện có (2)
        with self.factory() as db:
            setting = db.get(AppSetting, "cloud_last_attendance_id")
            self.assertIsNotNone(setting)
            self.assertEqual(int(setting.value), 2)

        # 3. Tạo 1 bản ghi mới sau lần đồng bộ đầu
        with self.factory() as db:
            # Tạo thêm 1 sinh viên mới để không bị vi phạm UniqueConstraint(session_id, student_id)
            st3 = Student(student_code="B23DCAT003", name="Lê Văn C", class_id=self.class_id)
            db.add(st3)
            db.flush()
            att3 = Attendance(session_id=self.session_id, student_id=st3.id, status="present")
            db.add(att3)
            db.commit()

        # 4. Lần đồng bộ tiếp theo: bản ghi mới được gửi lên Cloud
        res2 = cloud_sync.sync_once(url=self.mock_cloud.url, token="token", backfill=False)
        self.assertTrue(res2["ok"])
        self.assertEqual(res2["sent"], 1)
        self.assertEqual(len(self.mock_cloud.received_posts[1]["attendance"]), 1)
        self.assertEqual(self.mock_cloud.received_posts[1]["attendance"][0]["student_code"], "B23DCAT003")

    def test_device_snapshot_no_ip_address(self):
        """device_snapshot: không gửi ip_address lên cloud, chỉ có device_id, name, status, last_seen."""
        with self.factory() as db:
            rows = cloud_sync.device_snapshot(db)
            self.assertEqual(len(rows), 1)
            d = rows[0]
            self.assertEqual(set(d.keys()), {"device_id", "name", "status", "last_seen"})
            self.assertEqual(d["device_id"], "esp32-cam-01")
            self.assertNotIn("ip_address", d)

    def test_run_forever_cancellation(self):
        """run_forever thoát sạch khi nhận asyncio.CancelledError."""
        async def run_and_cancel():
            task = asyncio.create_task(cloud_sync.run_forever())
            await asyncio.sleep(0.01)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        asyncio.run(run_and_cancel())
