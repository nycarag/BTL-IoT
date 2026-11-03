import unittest
from unittest.mock import patch

import cv2
import numpy as np

import test_api
from app.services.camera_preview import PreviewStore, previews


class PreviewApiTests(unittest.TestCase):
    setUp = test_api.ApiTests.setUp
    tearDown = test_api.ApiTests.tearDown
    post = test_api.ApiTests.post
    frame = test_api.ApiTests.frame

    def test_authenticated_preview_without_attendance(self):
        previews.frames.clear()
        previews.results.clear()
        _, data = cv2.imencode(".jpg", np.zeros((160, 160, 3), dtype=np.uint8))
        response = self.client.post("/api/devices/cam/preview", headers=self.device,
                                    files={"image": ("frame.jpg", data.tobytes(), "image/jpeg")})
        self.assertEqual(response.status_code, 202, response.text)
        self.assertFalse(response.json()["accepted"])
        self.assertEqual(self.client.get("/api/devices/cam/preview.jpg").status_code, 401)
        image = self.client.get("/api/devices/cam/preview.jpg", headers=self.auth)
        self.assertEqual(image.content, data.tobytes())
        self.assertEqual(image.headers["cache-control"], "no-store, private")
        metadata = self.client.get("/api/devices/cam/preview", headers=self.auth).json()
        self.assertTrue(metadata["available"])
        self.assertEqual(metadata["result"]["state"], "preview")
        self.assertNotIn("image", metadata)
        self.assertEqual(self.client.get("/api/attendance", headers=self.auth).json(), [])

    def test_missing_or_expired_preview(self):
        previews.frames.clear()
        previews.results.clear()
        self.assertFalse(self.client.get("/api/devices/cam/preview", headers=self.auth).json()["available"])
        self.assertEqual(self.client.get("/api/devices/cam/preview.jpg", headers=self.auth).status_code, 404)

    def test_camera_websocket_sends_meta_when_result_changes(self):
        previews.frames.clear()
        previews.results.clear()
        token = self.auth["Authorization"].split()[1]
        _, data = cv2.imencode(".jpg", np.zeros((160, 160, 3), dtype=np.uint8))
        jpeg_bytes = data.tobytes()

        with self.client.websocket_connect("/ws/devices/cam/camera") as ws:
            ws.send_json({"token": token})

            # 1. Add preview frame -> receives binary frame
            previews.put("cam", jpeg_bytes, is_preview=True)
            frame_bytes = ws.receive_bytes()
            self.assertEqual(frame_bytes, jpeg_bytes)
            # Send ACK next
            ws.send_text("next")

            # 2. Simulate AI analysis result update
            seq_analysis = previews.begin_analysis("cam", jpeg_bytes, self.session_id)
            previews.update(
                "cam",
                seq_analysis,
                {
                    "accepted": True,
                    "student_code": "SV1",
                    "box": [20, 25, 60, 60],
                    "frame_size": [160, 160],
                },
            )

            # 3. Receives meta message with new AI result
            updated_meta = ws.receive_json()
            self.assertEqual(updated_meta["type"], "meta")
            self.assertTrue(updated_meta["result"]["accepted"])
            self.assertEqual(updated_meta["result"]["student_code"], "SV1")
            self.assertEqual(updated_meta["result"]["box"], [20, 25, 60, 60])
            self.assertIn("config", updated_meta)


class PreviewStoreTests(unittest.TestCase):
    def test_ttl_capacity_and_sequence(self):
        store = PreviewStore(ttl=10, capacity=2)
        with patch("app.services.camera_preview.time.monotonic", return_value=0):
            sequence = store.put("cam", b"first", 1)
            new_sequence = store.put("cam", b"new", 1)
            store.update("cam", sequence, {"accepted": True})
            self.assertNotIn("accepted", store.get("cam")["result"])
            store.update("cam", new_sequence, {"accepted": False})
            self.assertFalse(store.get("cam")["result"]["accepted"])
            store.put("cam2", b"second")
            store.put("cam3", b"third")
            self.assertIsNone(store.get("cam"))
        with patch("app.services.camera_preview.time.monotonic", return_value=11):
            self.assertIsNone(store.get("cam2"))
            self.assertEqual(len(store.frames), 0)
