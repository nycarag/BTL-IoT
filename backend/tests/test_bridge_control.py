"""Unit and integration tests for camera bridge lifecycle control and SSRF protection."""
import test_api

import subprocess
import unittest
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient

from app.services.bridge_control import BridgeControl, validate_camera_url


class BridgeControlUnitTests(unittest.TestCase):
    def test_validate_camera_url_accepts_private_and_loopback(self):
        valid_urls = [
            "http://192.168.4.1/capture",
            "http://192.168.1.100:80/capture",
            "http://10.0.0.5:8080/capture",
            "http://172.16.0.2/capture",
            "http://127.0.0.1:8000/capture",
            "http://localhost/capture",
            "https://192.168.4.1/capture",
        ]
        for url in valid_urls:
            self.assertEqual(validate_camera_url(url), url)

    def test_validate_camera_url_rejects_public_and_file_ssrf(self):
        invalid_urls = [
            ("http://8.8.8.8/capture", "not a private LAN or loopback"),
            ("http://1.1.1.1:80/capture", "not a private LAN or loopback"),
            ("file:///etc/passwd", "Invalid URL scheme"),
            ("ftp://192.168.4.1/capture", "Invalid URL scheme"),
            ("http://admin:secret@192.168.4.1/capture", "embedded user credentials"),
            ("", "non-empty string"),
        ]
        for url, expected_err in invalid_urls:
            with self.assertRaises(ValueError, msg=f"Should reject {url}") as ctx:
                validate_camera_url(url)
            self.assertIn(expected_err, str(ctx.exception))

    def test_start_webcam_uses_list_args_no_shell_and_hides_token(self):
        control = BridgeControl()
        mock_proc = Mock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 12345
        mock_proc.stderr = None

        with patch("app.services.bridge_control.subprocess.Popen", return_value=mock_proc) as mock_popen:
            res = control.start(source="webcam")
            self.assertTrue(res["running"])
            self.assertEqual(res["pid"], 12345)
            self.assertEqual(res["source"], "webcam")
            self.assertEqual(res["device_id"], "webcam-01")

            mock_popen.assert_called_once()
            args, kwargs = mock_popen.call_args
            cmd_list = args[0]
            self.assertIsInstance(cmd_list, list)
            self.assertIn("--webcam", cmd_list)
            self.assertFalse(kwargs.get("shell", False))

            # Secret token MUST be in env, NEVER in argv
            self.assertIn("DEVICE_TOKEN", kwargs["env"])
            for arg in cmd_list:
                self.assertNotIn("test-device-only", str(arg))

    def test_cannot_start_two_processes(self):
        control = BridgeControl()
        mock_proc = Mock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 9999
        mock_proc.stderr = None

        with patch("app.services.bridge_control.subprocess.Popen", return_value=mock_proc) as mock_popen:
            control.start(source="webcam")
            mock_popen.assert_called_once()
            with self.assertRaises(RuntimeError) as ctx:
                control.start(source="webcam")
            self.assertIn("already running", str(ctx.exception))
            mock_popen.assert_called_once()

    def test_start_esp32_with_socket_check(self):
        control = BridgeControl()
        mock_proc = Mock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 23456
        mock_proc.stderr = None

        with patch("app.services.bridge_control.socket.create_connection") as mock_conn, \
             patch("app.services.bridge_control.subprocess.Popen", return_value=mock_proc) as mock_popen:
            res = control.start(source="esp32", camera_url="http://192.168.4.1/capture")
            self.assertTrue(res["running"])
            self.assertEqual(res["device_id"], "esp32-cam-01")
            mock_conn.assert_called_once_with(("192.168.4.1", 80), timeout=3)
            mock_popen.assert_called_once()
            args, kwargs = mock_popen.call_args
            self.assertNotIn("--webcam", args[0])
            self.assertEqual(kwargs["env"]["CAMERA_CAPTURE_URL"], "http://192.168.4.1/capture")

    def test_start_esp32_unreachable_raises_oserror(self):
        control = BridgeControl()
        with patch("app.services.bridge_control.socket.create_connection", side_effect=TimeoutError("No route to host")), \
             patch("app.services.bridge_control.subprocess.Popen") as mock_popen:
            with self.assertRaises(OSError) as ctx:
                control.start(source="esp32", camera_url="http://192.168.4.1/capture")
            self.assertIn("Cannot connect to ESP32-CAM", str(ctx.exception))
            mock_popen.assert_not_called()

    def test_stop_terminates_and_kills_after_timeout(self):
        control = BridgeControl()
        mock_proc = Mock()
        mock_proc.poll.return_value = None
        mock_proc.stderr = None

        with patch("app.services.bridge_control.subprocess.Popen", return_value=mock_proc):
            control.start(source="webcam")

        # Case 1: Normal graceful termination within 3s
        mock_proc.wait.return_value = 0
        res = control.stop()
        self.assertFalse(res["running"])
        mock_proc.terminate.assert_called_once()
        mock_proc.wait.assert_called_once_with(timeout=3)
        mock_proc.kill.assert_not_called()

        # Case 2: Process hangs, kill after 3s timeout
        mock_proc.reset_mock()
        mock_proc.poll.return_value = None
        mock_proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="bridge", timeout=3), 0]
        control.process = mock_proc
        res = control.stop()
        self.assertFalse(res["running"])
        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()


class BridgeApiIntegrationTests(unittest.TestCase):
    setUp = test_api.ApiTests.setUp
    tearDown = test_api.ApiTests.tearDown
    post = test_api.ApiTests.post

    def test_bridge_endpoints_require_admin(self):
        self.assertEqual(self.client.get("/api/bridge/status").status_code, 401)
        self.assertEqual(self.client.post("/api/bridge/start", json={"source": "webcam"}).status_code, 401)
        self.assertEqual(self.client.post("/api/bridge/stop").status_code, 401)

    def test_get_bridge_status_authenticated(self):
        response = self.client.get("/api/bridge/status", headers=self.auth)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("running", data)
        self.assertIn("device_id", data)
        self.assertIn("recent_errors", data)

    def test_start_rejects_ssrf_public_ip(self):
        response = self.client.post(
            "/api/bridge/start",
            headers=self.auth,
            json={"source": "esp32", "camera_url": "http://8.8.8.8/capture"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("not a private LAN or loopback", response.json()["detail"])

    def test_start_rejects_file_scheme(self):
        response = self.client.post(
            "/api/bridge/start",
            headers=self.auth,
            json={"source": "esp32", "camera_url": "file:///etc/passwd"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid URL scheme", response.json()["detail"])

    def test_start_and_stop_flow_mocked(self):
        with patch("app.api.devices.bridge.start") as mock_start, \
             patch("app.api.devices.bridge.stop") as mock_stop:
            mock_start.return_value = {
                "running": True, "pid": 4321, "source": "webcam",
                "device_id": "webcam-01", "camera_url": None, "connected": False,
                "recent_errors": []
            }
            res_start = self.client.post("/api/bridge/start", headers=self.auth, json={"source": "webcam"})
            self.assertEqual(res_start.status_code, 200)
            self.assertTrue(res_start.json()["running"])
            self.assertEqual(res_start.json()["pid"], 4321)

            mock_stop.return_value = {
                "running": False, "pid": None, "source": None,
                "device_id": "webcam-01", "camera_url": None, "connected": False,
                "recent_errors": []
            }
            res_stop = self.client.post("/api/bridge/stop", headers=self.auth)
            self.assertEqual(res_stop.status_code, 200)
            self.assertFalse(res_stop.json()["running"])

    def test_start_duplicate_returns_400(self):
        with patch("app.api.devices.bridge.start", side_effect=RuntimeError("Camera bridge is already running")):
            res = self.client.post("/api/bridge/start", headers=self.auth, json={"source": "webcam"})
            self.assertEqual(res.status_code, 400)
            self.assertIn("already running", res.json()["detail"])

    def test_start_rejects_invalid_source_literal(self):
        res = self.client.post("/api/bridge/start", headers=self.auth, json={"source": "invalid_source"})
        self.assertEqual(res.status_code, 422)

    def test_lifespan_shuts_down_bridge(self):
        with patch("app.main.bridge.stop") as mock_stop:
            with TestClient(self.client.app):
                pass
            mock_stop.assert_called_once()
