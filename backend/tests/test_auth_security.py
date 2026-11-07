"""Tests for password hashing, token jti, revocation, logout, and login throttling."""

from __future__ import annotations

import base64
import hashlib
import hmac
import tempfile
import time
import unittest
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.security import (
    _signature,
    check_admin_password,
    hash_password,
    issue_token,
    login_throttle,
    revoke_token,
    verify_password,
    verify_token,
)
from app.database import Base, get_db
from app.main import create_app
from app.models import AuditLog, ClassRoom, AttendanceSession


class AuthSecurityTests(unittest.TestCase):
    def setUp(self):
        login_throttle.reset()
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{self.temp.name}/test.db",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(self.engine, expire_on_commit=False)
        self.app = create_app()

        def db_override():
            with self.factory() as session:
                yield session

        self.app.dependency_overrides[get_db] = db_override
        self.client = TestClient(self.app)

    def tearDown(self):
        login_throttle.reset()
        self.temp.cleanup()

    @contextmanager
    def patch_settings(self, **kwargs):
        """Helper để patch an toàn các trường trên Settings (kể cả khi frozen)."""
        old_values = {}
        for k, v in kwargs.items():
            old_values[k] = getattr(settings, k, None)
            object.__setattr__(settings, k, v)
        try:
            yield
        finally:
            for k, v in old_values.items():
                if v is None:
                    try:
                        object.__delattr__(settings, k)
                    except Exception:
                        pass
                else:
                    object.__setattr__(settings, k, v)

    def test_hash_and_verify_password(self):
        # 1. Hash và verify đúng mật khẩu
        pw = "MySecretPass_123"
        hashed = hash_password(pw, iterations=10_000)
        self.assertTrue(hashed.startswith("pbkdf2_sha256$10000$"))
        self.assertTrue(verify_password(pw, hashed))

        # 2. Sai mật khẩu -> False
        self.assertFalse(verify_password("WrongPassword", hashed))

        # 3. Chuỗi hỏng / sai định dạng -> False
        self.assertFalse(verify_password(pw, "invalid_string"))
        self.assertFalse(verify_password(pw, "pbkdf2_sha256$notanumber$salt$hash"))
        self.assertFalse(verify_password(pw, "pbkdf2_sha256$0$salt$hash"))
        self.assertFalse(verify_password(pw, "pbkdf2_sha256$-100$salt$hash"))
        self.assertFalse(verify_password(pw, "pbkdf2_sha256$1000$salt"))
        self.assertFalse(verify_password(pw, ""))
        self.assertFalse(verify_password(pw, None))

    def test_admin_password_hash_login(self):
        secret_pw = "CustomAdminPass_456"
        hashed = hash_password(secret_pw, iterations=10_000)

        with self.patch_settings(admin_password_hash=hashed):
            # Đăng nhập với mật khẩu đúng
            res_ok = self.client.post(
                "/api/auth/login",
                json={"username": settings.admin_username, "password": secret_pw},
            )
            self.assertEqual(res_ok.status_code, 200)
            self.assertIn("access_token", res_ok.json())

            # Đăng nhập với mật khẩu sai
            res_bad = self.client.post(
                "/api/auth/login",
                json={"username": settings.admin_username, "password": "WrongPassword"},
            )
            self.assertEqual(res_bad.status_code, 401)
            self.assertEqual(res_bad.json()["detail"], "Invalid credentials")

    def test_login_throttling_and_rate_limiting(self):
        username = settings.admin_username

        # Gửi 4 lần sai -> vẫn nhận 401
        for i in range(4):
            res = self.client.post(
                "/api/auth/login",
                json={"username": username, "password": f"bad_pwd_{i}"},
            )
            self.assertEqual(res.status_code, 401, f"Attempt {i+1} should be 401")

        # Lần thứ 5 sai -> bị khóa ngay lập tức, trả về 429
        res_5 = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": "bad_pwd_5"},
        )
        self.assertEqual(res_5.status_code, 429)
        self.assertIn("Retry-After", res_5.headers)
        self.assertIn("Đăng nhập sai quá nhiều lần, thử lại sau", res_5.json()["detail"])

        # Trong lúc bị khóa, kể cả nhập đúng mật khẩu vẫn phải trả về 429
        valid_password = settings.admin_password or "test-password-only"
        res_locked = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": valid_password},
        )
        self.assertEqual(res_locked.status_code, 429)
        self.assertIn("Retry-After", res_locked.headers)
        self.assertIn("Đăng nhập sai quá nhiều lần, thử lại sau", res_locked.json()["detail"])

    def test_logout_and_token_revocation(self):
        valid_password = settings.admin_password or "test-password-only"

        # Lấy token 1
        res1 = self.client.post(
            "/api/auth/login",
            json={"username": settings.admin_username, "password": valid_password},
        )
        self.assertEqual(res1.status_code, 200)
        token1 = res1.json()["access_token"]

        # Lấy token 2
        res2 = self.client.post(
            "/api/auth/login",
            json={"username": settings.admin_username, "password": valid_password},
        )
        self.assertEqual(res2.status_code, 200)
        token2 = res2.json()["access_token"]

        # Dùng token 1 gọi endpoint được bảo vệ -> 200
        res_classes = self.client.get("/api/classes", headers={"Authorization": f"Bearer {token1}"})
        self.assertEqual(res_classes.status_code, 200)

        # Đăng xuất với token 1 -> 204 No Content
        res_logout = self.client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token1}"})
        self.assertEqual(res_logout.status_code, 204)

        # Thử dùng lại token 1 -> 401 Invalid or expired token
        res_classes_revoked = self.client.get(
            "/api/classes",
            headers={"Authorization": f"Bearer {token1}"},
        )
        self.assertEqual(res_classes_revoked.status_code, 401)
        self.assertEqual(res_classes_revoked.json()["detail"], "Invalid or expired token")

        # Token 2 vẫn sử dụng bình thường
        res_classes_token2 = self.client.get(
            "/api/classes",
            headers={"Authorization": f"Bearer {token2}"},
        )
        self.assertEqual(res_classes_token2.status_code, 200)

    def test_old_format_token_rejected(self):
        # Tạo token kiểu cũ chỉ gồm 2 phần "username:expiry"
        username = settings.admin_username
        expiry = int(time.time()) + 3600
        old_payload = f"{username}:{expiry}"
        encoded = base64.urlsafe_b64encode(old_payload.encode("utf-8")).decode("ascii").rstrip("=")
        signature = _signature(encoded)
        old_token = f"{encoded}.{signature}"

        res = self.client.get("/api/classes", headers={"Authorization": f"Bearer {old_token}"})
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["detail"], "Invalid or expired token")

    def test_audit_log_records_without_password(self):
        sensitive_password = "SuperSecretPlainTextPassword_DO_NOT_LEAK"

        self.client.post(
            "/api/auth/login",
            json={"username": "attacker", "password": sensitive_password},
        )

        with self.factory() as db:
            logs = list(db.scalars(select(AuditLog).where(AuditLog.action == "auth.login_failed")))
            self.assertGreaterEqual(len(logs), 1)
            last_log = logs[-1]
            self.assertEqual(last_log.actor, "anonymous")
            self.assertEqual(last_log.target, "attacker")
            # Tuyệt đối không chứa mật khẩu trong detail hay target
            self.assertNotIn(sensitive_password, last_log.detail or "")
            self.assertNotIn(sensitive_password, last_log.target or "")

    def test_websocket_auth_with_new_token(self):
        valid_password = settings.admin_password or "test-password-only"
        res = self.client.post(
            "/api/auth/login",
            json={"username": settings.admin_username, "password": valid_password},
        )
        token = res.json()["access_token"]

        # Tạo 1 session trong DB để websocket không bị close với code 4404
        with self.factory() as db:
            c = ClassRoom(code="D21_TEST", name="Class Test")
            db.add(c)
            db.commit()
            db.refresh(c)
            s = AttendanceSession(class_id=c.id, title="Buổi test websocket")
            db.add(s)
            db.commit()
            db.refresh(s)
            session_id = s.id

        with self.client.websocket_connect(f"/ws/sessions/{session_id}") as ws:
            ws.send_json({"token": token})
            msg = ws.receive_json()
            self.assertEqual(msg, {"type": "ready"})
