"""Tests for CAMERA_DEVICE_NAME configuration in camera_bridge heartbeats."""
from unittest.mock import Mock, patch
from urllib.parse import urlparse

import pytest
from camera_bridge import CameraBridge, device_name, main


def test_device_name_helper_fallback_when_unset(monkeypatch):
    monkeypatch.delenv("CAMERA_DEVICE_NAME", raising=False)
    assert device_name("Default Name") == "Default Name"


def test_device_name_helper_fallback_when_empty_or_whitespace(monkeypatch):
    monkeypatch.setenv("CAMERA_DEVICE_NAME", "")
    assert device_name("Default Name") == "Default Name"

    monkeypatch.setenv("CAMERA_DEVICE_NAME", "   \t\n  ")
    assert device_name("Default Name") == "Default Name"


def test_device_name_helper_custom_value_stripped(monkeypatch):
    monkeypatch.setenv("CAMERA_DEVICE_NAME", "  Điện thoại · camera IP  ")
    assert device_name("Default Name") == "Điện thoại · camera IP"


def test_device_name_helper_max_length_255(monkeypatch):
    long_name = "A" * 300
    monkeypatch.setenv("CAMERA_DEVICE_NAME", long_name)
    result = device_name("Default Name")
    assert len(result) == 255
    assert result == "A" * 255


def test_tick_heartbeat_uses_default_when_unset(monkeypatch):
    monkeypatch.delenv("CAMERA_DEVICE_NAME", raising=False)
    bridge = CameraBridge("http://192.168.4.1/capture", "http://localhost:8000", "cam", "test-token")
    bridge.capture = Mock(return_value=b"jpeg")
    bridge.api = Mock(side_effect=[{}, {"session_id": None, "active": False}, {"preview": True}])

    bridge.tick(0)

    heartbeat_call = bridge.api.call_args_list[0]
    assert heartbeat_call.args[0] == "/devices/heartbeat"
    assert heartbeat_call.args[1]["name"] == "ESP32-CAM · SoftAP bridge"
    assert heartbeat_call.args[1]["ip_address"] == "192.168.4.1"


def test_tick_heartbeat_uses_custom_name_when_set(monkeypatch):
    monkeypatch.setenv("CAMERA_DEVICE_NAME", "Điện thoại · camera IP")
    bridge = CameraBridge("http://192.168.1.15:8080/shot.jpg", "http://localhost:8000", "phone-cam-02", "test-token")
    bridge.capture = Mock(return_value=b"jpeg")
    bridge.api = Mock(side_effect=[{}, {"session_id": None, "active": False}, {"preview": True}])

    bridge.tick(0)

    heartbeat_call = bridge.api.call_args_list[0]
    assert heartbeat_call.args[0] == "/devices/heartbeat"
    assert heartbeat_call.args[1]["name"] == "Điện thoại · camera IP"
    assert heartbeat_call.args[1]["ip_address"] == "192.168.1.15"


def test_main_check_url_branch_default_and_custom(monkeypatch):
    with patch("camera_bridge.load_env"):
        # 1. Unset: defaults to ESP32-CAM · SoftAP bridge
        monkeypatch.delenv("CAMERA_DEVICE_NAME", raising=False)
        monkeypatch.setattr("sys.argv", ["camera_bridge.py", "--check"])

        mock_bridge = Mock()
        mock_bridge.capture.return_value = b"\xff\xd8\xff\xd9"
        mock_bridge.camera_url = "http://192.168.4.1/capture"
        mock_bridge.api.return_value = {"session_id": 1, "active": True}

        with patch("camera_bridge.CameraBridge", return_value=mock_bridge):
            main()

        hb_call = mock_bridge.api.call_args_list[0]
        assert hb_call.args[0] == "/devices/heartbeat"
        assert hb_call.args[1]["name"] == "ESP32-CAM · SoftAP bridge"
        assert hb_call.args[1]["ip_address"] == "192.168.4.1"

        # 2. Set: uses custom device name
        monkeypatch.setenv("CAMERA_DEVICE_NAME", "Điện thoại · camera IP")
        mock_bridge.reset_mock()
        mock_bridge.api.return_value = {"session_id": 1, "active": True}

        with patch("camera_bridge.CameraBridge", return_value=mock_bridge):
            main()

        hb_call = mock_bridge.api.call_args_list[0]
        assert hb_call.args[0] == "/devices/heartbeat"
        assert hb_call.args[1]["name"] == "Điện thoại · camera IP"
        assert hb_call.args[1]["ip_address"] == "192.168.4.1"


def test_main_check_webcam_branch_default_and_custom(monkeypatch):
    with patch("camera_bridge.load_env"):
        # 1. Unset: defaults to Laptop Webcam Local
        monkeypatch.delenv("CAMERA_DEVICE_NAME", raising=False)
        monkeypatch.setattr("sys.argv", ["camera_bridge.py", "--check", "--webcam"])

        mock_bridge = Mock()
        mock_bridge.capture.return_value = b"\xff\xd8\xff\xd9"
        mock_bridge.api.return_value = {"session_id": 1, "active": True}

        with patch("camera_bridge.CameraBridge", return_value=mock_bridge):
            main()

        hb_call = mock_bridge.api.call_args_list[0]
        assert hb_call.args[0] == "/devices/heartbeat"
        assert hb_call.args[1]["name"] == "Laptop Webcam Local"
        assert hb_call.args[1]["ip_address"] == "127.0.0.1"

        # 2. Set: uses custom device name
        monkeypatch.setenv("CAMERA_DEVICE_NAME", "Điện thoại · camera IP")
        mock_bridge.reset_mock()
        mock_bridge.api.return_value = {"session_id": 1, "active": True}

        with patch("camera_bridge.CameraBridge", return_value=mock_bridge):
            main()

        hb_call = mock_bridge.api.call_args_list[0]
        assert hb_call.args[0] == "/devices/heartbeat"
        assert hb_call.args[1]["name"] == "Điện thoại · camera IP"
        assert hb_call.args[1]["ip_address"] == "127.0.0.1"


def test_preview_worker_heartbeat_url_and_webcam(monkeypatch):
    """Test preview_worker loop in run() for both URL and webcam branches."""
    # Setup bridge for URL branch (cap is None)
    bridge_url = CameraBridge("http://192.168.1.15:8080/shot.jpg", "http://localhost:8000", "phone-cam-02", "test-token")
    assert bridge_url.cap is None

    # Setup bridge for Webcam branch (simulate cap is not None)
    bridge_cam = CameraBridge("http://192.168.4.1/capture", "http://localhost:8000", "webcam-01", "test-token")
    bridge_cam.cap = Mock()

    # Helper to capture preview_worker and run 1 iteration
    def capture_and_run_preview(bridge):
        workers = {}
        mock_stop_event = None

        def fake_thread(target, name, **kwargs):
            workers[name] = target
            m = Mock()
            m.is_alive.return_value = True
            return m

        with patch("threading.Thread", side_effect=fake_thread), \
             patch("camera_bridge.LatestFrame") as mock_latest_cls, \
             patch("camera_bridge.BackendConnection") as mock_backend_cls, \
             patch("camera_bridge.infer_stream_url", return_value="http://192.168.1.15:8080/video"):

            latest_inst = Mock()
            # First call returns frame, second returns None to stop
            latest_inst.get.side_effect = [(1, b"frame-data"), None]
            mock_latest_cls.return_value = latest_inst

            backend_inst = Mock()
            mock_backend_cls.return_value = backend_inst

            # Intercept stop.wait to stop the main run loop immediately
            with patch("threading.Event") as mock_event_cls:
                real_stop = Mock()
                real_stop.is_set.side_effect = [False, True]
                mock_event_cls.return_value = real_stop

                bridge.run()

            # Now workers["preview"] is captured. Let's run it.
            preview_worker = workers["preview"]
            preview_worker()
            return backend_inst

    # URL branch: default vs custom
    monkeypatch.delenv("CAMERA_DEVICE_NAME", raising=False)
    backend_url_default = capture_and_run_preview(bridge_url)
    backend_url_default.json.assert_called_with("/devices/heartbeat", {"name": "ESP32-CAM · MJPEG bridge", "ip_address": "192.168.1.15"})

    monkeypatch.setenv("CAMERA_DEVICE_NAME", "Điện thoại · camera IP")
    backend_url_custom = capture_and_run_preview(bridge_url)
    backend_url_custom.json.assert_called_with("/devices/heartbeat", {"name": "Điện thoại · camera IP", "ip_address": "192.168.1.15"})

    # Webcam branch: default vs custom
    monkeypatch.delenv("CAMERA_DEVICE_NAME", raising=False)
    backend_cam_default = capture_and_run_preview(bridge_cam)
    backend_cam_default.json.assert_called_with("/devices/heartbeat", {"name": "Laptop Webcam Local", "ip_address": "127.0.0.1"})

    monkeypatch.setenv("CAMERA_DEVICE_NAME", "Điện thoại · camera IP")
    backend_cam_custom = capture_and_run_preview(bridge_cam)
    backend_cam_custom.json.assert_called_with("/devices/heartbeat", {"name": "Điện thoại · camera IP", "ip_address": "127.0.0.1"})
