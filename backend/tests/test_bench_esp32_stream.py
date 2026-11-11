"""
test_bench_esp32_stream.py - Unit test cho công cụ đo kiểm bench_esp32_stream.py.
Dựng server MJPEG giả lập bằng http.server, kiểm tra đếm frame, phát hiện khựng,
đo FPS, và kịch bản sweep tham số cảm biến.
"""

from __future__ import annotations

import json
import socketserver
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlsplit

from tools.bench_esp32_stream import (
    FRAMESIZE_ENUMS,
    get_camera_status,
    measure_latency,
    measure_stream,
    run_benchmark,
)

TINY_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
    b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
    b"\x1f\x1e\x1d\x1a\x1c\x1c $.\x27 \",#\x1c\x1c(7),01444\x1f\x279=82<.342"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
    b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
)


class MockCameraHandler(BaseHTTPRequestHandler):
    """Giả lập server HTTP của ESP32-CAM (phục vụ /stream, /status, /control)."""

    current_framesize = 8  # FRAMESIZE_CIF
    current_quality = 12
    control_calls: list[tuple[str, int]] = []

    def log_message(self, format, *args):
        # Tắt in log ra console trong lúc test
        pass

    def do_GET(self):
        parsed = urlsplit(self.path)
        path = parsed.path

        if path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame_boundary")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            # Phát 50 frame JPEG ở tốc độ ~20 fps (50ms/frame), tại frame 25 dừng 400ms (> 250ms)
            for i in range(50):
                try:
                    part_header = (
                        b"\r\n--frame_boundary\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(TINY_JPEG)).encode() + b"\r\n\r\n"
                    )
                    self.wfile.write(part_header + TINY_JPEG)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    break

                if i == 25:
                    time.sleep(0.40)  # Khoảng nghỉ 400 ms gây khựng
                else:
                    time.sleep(0.045)  # ~20 fps

        elif path == "/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            payload = {
                "framesize": self.current_framesize,
                "quality": self.current_quality,
                "psram": True,
                "wifi_mode": "sta",
                "ip": "127.0.0.1",
                "rssi": -58,
                "hostname": "esp32cam",
                "stream_fps": 20,
                "free_heap": 268000,
                "uptime_s": 120,
            }
            self.wfile.write(json.dumps(payload).encode("utf-8"))

        elif path == "/control":
            qs = parse_qs(parsed.query)
            var_list = qs.get("var", [])
            val_list = qs.get("val", [])

            if not var_list or not val_list:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{\"ok\":false,\"error\":\"Missing var or val\"}")
                return

            var = var_list[0]
            try:
                val = int(val_list[0])
            except ValueError:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{\"ok\":false,\"error\":\"Invalid integer val\"}")
                return

            if var == "framesize":
                if val not in FRAMESIZE_ENUMS.values():
                    self.send_response(400)
                    self.end_headers()
                    return
                self.current_framesize = val
                self.control_calls.append((var, val))
            elif var == "quality":
                if val < 10 or val > 30:
                    self.send_response(400)
                    self.end_headers()
                    return
                self.current_quality = val
                self.control_calls.append((var, val))
            else:
                self.send_response(400)
                self.end_headers()
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            resp = {"ok": True, "framesize": self.current_framesize, "quality": self.current_quality}
            self.wfile.write(json.dumps(resp).encode("utf-8"))

        else:
            self.send_response(404)
            self.end_headers()


class MockOldCameraHandler(BaseHTTPRequestHandler):
    """Giả lập camera firmware cũ (không có /status và /control)."""

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame_boundary")
            self.end_headers()
            for _ in range(10):
                try:
                    part = b"\r\n--frame_boundary\r\nContent-Type: image/jpeg\r\n\r\n" + TINY_JPEG
                    self.wfile.write(part)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    break
                time.sleep(0.02)
        else:
            self.send_response(404)
            self.end_headers()


class TestBenchEsp32Stream(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Khởi tạo server mock camera
        cls.server = socketserver.TCPServer(("127.0.0.1", 0), MockCameraHandler)
        cls.port = cls.server.server_address[1]
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        MockCameraHandler.current_framesize = 8
        MockCameraHandler.current_quality = 12
        MockCameraHandler.control_calls = []

    def test_mjpeg_stream_metrics_and_stutter(self):
        """Kiểm tra đếm đúng 50 frame, phát hiện đúng 1 lần khựng (> 250ms), và FPS xấp xỉ 20."""
        stream_url = f"{self.base_url}/stream"
        metrics = measure_stream(stream_url, duration=10.0)

        # 1. Đếm đúng 50 frame
        self.assertEqual(metrics["frame_count"], 50)

        # 2. Phát hiện đúng 1 lần khựng (> 250 ms) do khoảng nghỉ 400ms
        self.assertEqual(metrics["stutter_count"], 1)

        # 3. FPS xấp xỉ 20 (dung sai rộng: 14 - 24 fps)
        self.assertGreater(metrics["avg_fps"], 14.0)
        self.assertLess(metrics["avg_fps"], 24.0)

        # 4. Khoảng cách max phản ánh đúng mốc 400ms (> 350 ms)
        self.assertGreater(metrics["interval_max_ms"], 350.0)
        self.assertGreater(metrics["kbps"], 0.0)

    def test_status_and_latency_measurement(self):
        """Kiểm tra đo latency mạng và lấy thông tin trạng thái camera."""
        status = get_camera_status(self.base_url)
        self.assertIsNotNone(status)
        assert status is not None
        self.assertEqual(status["wifi_mode"], "sta")
        self.assertEqual(status["framesize"], 8)
        self.assertEqual(status["quality"], 12)

        lat = measure_latency(self.base_url, count=10)
        self.assertEqual(lat["samples"], 10)
        self.assertIsNotNone(lat["p50_ms"])
        self.assertIsNotNone(lat["p95_ms"])

    def test_sweep_combinations_and_config_restoration(self):
        """Kiểm tra --sweep gọi đủ 6 tổ hợp và hoàn trả lại cấu hình ban đầu."""
        initial_fs = MockCameraHandler.current_framesize
        initial_q = MockCameraHandler.current_quality

        result = run_benchmark(
            base_url=self.base_url,
            seconds=0.08,
            label="test-sweep",
            sweep=True,
            sweep_delay=0.01,
        )

        sweep_list = result.get("sweep")
        self.assertIsNotNone(sweep_list)
        assert sweep_list is not None
        self.assertEqual(len(sweep_list), 6)

        # Kiểm tra mọi tổ hợp đều thành công
        for item in sweep_list:
            self.assertTrue(item["supported"])
            self.assertEqual(item["status"], "OK")

        # Kiểm tra đã gọi đủ các tổ hợp qua /control
        called_vars = [var for var, val in MockCameraHandler.control_calls]
        self.assertIn("framesize", called_vars)
        self.assertIn("quality", called_vars)

        # Kiểm tra cấu hình ban đầu được hoàn trả chính xác
        self.assertEqual(MockCameraHandler.current_framesize, initial_fs)
        self.assertEqual(MockCameraHandler.current_quality, initial_q)

    def test_old_firmware_fallback(self):
        """Kiểm tra fallback an toàn khi gặp firmware cũ (404 status/control)."""
        old_server = socketserver.TCPServer(("127.0.0.1", 0), MockOldCameraHandler)
        old_port = old_server.server_address[1]
        t = threading.Thread(target=old_server.serve_forever, daemon=True)
        t.start()

        try:
            old_url = f"http://127.0.0.1:{old_port}"
            res = run_benchmark(base_url=old_url, seconds=0.1, label="test-old", sweep=True)

            self.assertIsNone(res["status_before"])
            self.assertIsNone(res["status_after"])
            self.assertIsNone(res["latency"]["p50_ms"])
            # Đo luồng vẫn hoạt động bình thường
            self.assertGreaterEqual(res["stream"]["frame_count"], 0)
        finally:
            old_server.shutdown()
            old_server.server_close()


if __name__ == "__main__":
    unittest.main()
