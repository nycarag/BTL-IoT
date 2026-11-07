"""Tests for administrative audit logs API."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

os.environ["ADMIN_PASSWORD"] = "test-password-only"
os.environ["DEVICE_TOKEN"] = "test-device-only"
os.environ["FRAME_INTERVAL_SECONDS"] = "0"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import audit
from app.database import Base, get_db
from app.main import create_app
from app.models.school import AuditLog
from app.services.audit import log_action


class AuditApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{self.temp.name}/test.db",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(self.engine, expire_on_commit=False)

        app = create_app()
        app.include_router(audit.router, prefix="/api")
        # Đảm bảo Mount của StaticFiles luôn nằm cuối danh sách route
        mounts = [r for r in app.routes if type(r).__name__ == "Mount"]
        for m in mounts:
            app.routes.remove(m)
            app.routes.append(m)

        def override_db():
            with self.factory() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

        # Lấy token quản trị
        resp = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "test-password-only"},
        )
        token = resp.json()["access_token"]
        self.auth = {"Authorization": f"Bearer {token}"}

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.temp.cleanup()

    def _seed_sample_logs(self):
        with self.factory() as db:
            # Xóa các log phát sinh từ bước login trong setUp để có trạng thái độc lập
            db.query(AuditLog).delete()
            db.commit()

            log_action(
                db,
                actor="admin",
                action="auth.login",
                target=None,
                detail={"ip": "127.0.0.1"},
                ip_address="127.0.0.1",
            )
            log_action(
                db,
                actor="admin",
                action="auth.logout",
                target=None,
                detail={"reason": "user_logout"},
                ip_address="127.0.0.1",
            )
            log_action(
                db,
                actor="anonymous",
                action="auth.login_failed",
                target="admin",
                detail={"reason": "wrong_password"},
                ip_address="10.0.0.1",
            )
            log_action(
                db,
                actor="admin",
                action="students.import",
                target=None,
                detail={"filename": "danh_sach.csv", "created": 20, "updated": 0, "skipped": 0},
                ip_address="127.0.0.1",
            )
            log_action(
                db,
                actor="admin",
                action="students.export",
                target=None,
                detail={"format": "csv", "count": 20},
                ip_address="127.0.0.1",
            )
            log_action(
                db,
                actor="admin",
                action="schedules.export",
                target=None,
                detail={"format": "ics", "count": 5},
                ip_address="127.0.0.1",
            )
            # Thêm bản ghi có detail không phải JSON
            raw_entry = AuditLog(
                actor="system",
                action="system.alert",
                target="storage",
                detail="Raw unparsed alert message without JSON",
                ip_address=None,
            )
            db.add(raw_entry)
            db.commit()

    def test_unauthenticated_returns_401(self):
        """Không có token -> 401."""
        res = self.client.get("/api/audit-logs")
        self.assertEqual(res.status_code, 401)

    def test_list_all_audit_logs_order_desc(self):
        """Lấy toàn bộ nhật ký sắp xếp theo id giảm dần."""
        self._seed_sample_logs()
        res = self.client.get("/api/audit-logs", headers=self.auth)
        self.assertEqual(res.status_code, 200)
        logs = res.json()
        self.assertEqual(len(logs), 7)

        # Kiểm tra id giảm dần
        ids = [log["id"] for log in logs]
        self.assertEqual(ids, sorted(ids, reverse=True))

        # Kiểm tra cấu trúc các trường trả về
        first = logs[0]
        self.assertIn("id", first)
        self.assertIn("actor", first)
        self.assertIn("action", first)
        self.assertIn("target", first)
        self.assertIn("detail", first)
        self.assertIn("ip_address", first)
        self.assertIn("created_at", first)

    def test_detail_json_object_and_fallback_raw_string(self):
        """detail được parse thành object JSON, nếu lỗi parse thì trả chuỗi gốc."""
        self._seed_sample_logs()
        res = self.client.get("/api/audit-logs", headers=self.auth)
        self.assertEqual(res.status_code, 200)
        logs = res.json()

        # Bản ghi system.alert có chuỗi gốc
        alert_log = next(log for log in logs if log["action"] == "system.alert")
        self.assertEqual(alert_log["detail"], "Raw unparsed alert message without JSON")

        # Bản ghi auth.login có detail là dict
        login_log = next(log for log in logs if log["action"] == "auth.login")
        self.assertIsInstance(login_log["detail"], dict)
        self.assertEqual(login_log["detail"]["ip"], "127.0.0.1")

    def test_filter_exact_action(self):
        """Lọc action khớp chính xác."""
        self._seed_sample_logs()
        res = self.client.get(
            "/api/audit-logs?action=students.import",
            headers=self.auth,
        )
        self.assertEqual(res.status_code, 200)
        logs = res.json()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["action"], "students.import")
        self.assertEqual(logs[0]["detail"]["filename"], "danh_sach.csv")

    def test_filter_prefix_action(self):
        """Lọc tiền tố khi action kết thúc bằng dấu chấm (ví dụ 'auth.')."""
        self._seed_sample_logs()
        res = self.client.get("/api/audit-logs?action=auth.", headers=self.auth)
        self.assertEqual(res.status_code, 200)
        logs = res.json()
        self.assertEqual(len(logs), 3)
        actions = {log["action"] for log in logs}
        self.assertEqual(actions, {"auth.login", "auth.logout", "auth.login_failed"})

    def test_pagination_limit_and_offset(self):
        """Phân trang limit và offset chính xác."""
        self._seed_sample_logs()
        res_p1 = self.client.get(
            "/api/audit-logs?limit=3&offset=0",
            headers=self.auth,
        )
        self.assertEqual(res_p1.status_code, 200)
        logs_p1 = res_p1.json()
        self.assertEqual(len(logs_p1), 3)

        res_p2 = self.client.get(
            "/api/audit-logs?limit=3&offset=3",
            headers=self.auth,
        )
        self.assertEqual(res_p2.status_code, 200)
        logs_p2 = res_p2.json()
        self.assertEqual(len(logs_p2), 3)

        ids_p1 = [l["id"] for l in logs_p1]
        ids_p2 = [l["id"] for l in logs_p2]
        # Hai trang không được trùng nhau
        self.assertTrue(set(ids_p1).isdisjoint(set(ids_p2)))

    def test_limit_zero_or_exceed_returns_422(self):
        """limit=0 -> 422, limit > 500 -> 422, offset < 0 -> 422."""
        res_zero = self.client.get("/api/audit-logs?limit=0", headers=self.auth)
        self.assertEqual(res_zero.status_code, 422)

        res_over = self.client.get("/api/audit-logs?limit=501", headers=self.auth)
        self.assertEqual(res_over.status_code, 422)

        res_neg = self.client.get("/api/audit-logs?offset=-1", headers=self.auth)
        self.assertEqual(res_neg.status_code, 422)

    def test_read_only_endpoint(self):
        """Endpoint chỉ đọc, không cho phép POST hoặc DELETE."""
        res_post = self.client.post("/api/audit-logs", headers=self.auth)
        self.assertEqual(res_post.status_code, 405)

        res_delete = self.client.delete("/api/audit-logs", headers=self.auth)
        self.assertEqual(res_delete.status_code, 405)
