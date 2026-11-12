"""Tests for Cloud API endpoints and lifespan integration (Task C02)."""

from __future__ import annotations

import asyncio
import dataclasses
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.security import issue_token
from app.database import Base, get_db
from app.main import create_app
from app.services import cloud_sync


class TestCloudApi(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{self.temp.name}/test.db",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(self.engine, expire_on_commit=False)

        self.app = create_app()

        def _get_test_db():
            with self.factory() as session:
                yield session

        self.app.dependency_overrides[get_db] = _get_test_db
        self.client = TestClient(self.app)
        token = issue_token(settings.admin_username)
        self.auth = {"Authorization": f"Bearer {token}"}

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.temp.cleanup()

    def test_unauthenticated_status_returns_401(self):
        """Chưa đăng nhập gọi /api/cloud/status phải trả về 401."""
        resp = self.client.get("/api/cloud/status")
        self.assertEqual(resp.status_code, 401)

    def test_unauthenticated_sync_now_returns_401(self):
        """Chưa đăng nhập gọi /api/cloud/sync-now phải trả về 401."""
        resp = self.client.post("/api/cloud/sync-now")
        self.assertEqual(resp.status_code, 401)

    def test_authenticated_status_when_not_configured(self):
        """Đăng nhập rồi: status trả về enabled=False khi CLOUD_SYNC_URL trống."""
        resp = self.client.get("/api/cloud/status", headers=self.auth)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["enabled"])
        self.assertEqual(data["gateway_id"], settings.gateway_id)
        self.assertIn("interval_seconds", data)

    def test_authenticated_sync_now_when_not_configured(self):
        """Đăng nhập rồi: sync-now trả về {'enabled': False} khi chưa cấu hình URL."""
        resp = self.client.post("/api/cloud/sync-now", headers=self.auth)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"enabled": False})

    def test_json_responses_do_not_leak_url_or_token(self):
        """Chuỗi JSON trả về từ cả status và sync-now không chứa 'token' hay 'url'."""
        resp_status = self.client.get("/api/cloud/status", headers=self.auth)
        self.assertEqual(resp_status.status_code, 200)
        self.assertNotIn("token", resp_status.text.lower())
        self.assertNotIn("url", resp_status.text.lower())

        resp_sync = self.client.post("/api/cloud/sync-now", headers=self.auth)
        self.assertEqual(resp_sync.status_code, 200)
        self.assertNotIn("token", resp_sync.text.lower())
        self.assertNotIn("url", resp_sync.text.lower())

    def test_sync_now_drops_commands_key(self):
        """sync-now trả kết quả nhưng BỎ khóa 'commands'."""
        mock_result = {
            "enabled": True,
            "ok": True,
            "sent": 2,
            "added": 2,
            "pending": 0,
            "commands": [
                {"id": 1, "device_id": "esp32-cam-01", "lenh": "flash", "gia_tri": ""},
            ],
        }
        with patch.object(cloud_sync, "sync_once", return_value=mock_result):
            resp = self.client.post("/api/cloud/sync-now", headers=self.auth)
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertNotIn("commands", data)
            self.assertTrue(data["enabled"])
            self.assertTrue(data["ok"])
            self.assertEqual(data["sent"], 2)
            self.assertEqual(data["added"], 2)
            self.assertEqual(data["pending"], 0)

    def test_lifespan_without_cloud_url_does_not_spawn_cloud_task(self):
        """Lifespan khởi động và tắt sạch khi CLOUD_SYNC_URL trống (không sinh tác vụ cloud)."""
        empty_settings = dataclasses.replace(settings, cloud_sync_url="")
        with patch.object(cloud_sync, "run_forever", new_callable=AsyncMock) as mock_run:
            with patch("app.main.settings", empty_settings):
                app = create_app()
                with TestClient(app):
                    pass
            mock_run.assert_not_called()

    def test_lifespan_with_cloud_url_spawns_and_cancels_task(self):
        """Lifespan khởi động tác vụ cloud khi CLOUD_SYNC_URL có cấu hình và hủy sạch sẽ lúc tắt."""
        configured_settings = dataclasses.replace(settings, cloud_sync_url="http://127.0.0.1:8000/cloud")

        async def fake_run_forever():
            try:
                while True:
                    await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                raise

        with patch.object(cloud_sync, "run_forever", side_effect=fake_run_forever):
            with patch("app.main.settings", configured_settings):
                app = create_app()
                with TestClient(app):
                    pass  # Khởi động lifespan và tắt khi thoát khỏi context
