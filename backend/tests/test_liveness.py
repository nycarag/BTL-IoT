"""Unit tests for active liveness service (EAR blink detection) and pipeline gate."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

os.environ["ADMIN_PASSWORD"] = "test-password-only"
os.environ["DEVICE_TOKEN"] = "test-device-only"
os.environ["FRAME_INTERVAL_SECONDS"] = "0"
os.environ["LIVENESS_MODE"] = "blink"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import create_app
from app.models.school import FaceReference
from app.services.antispoof import PadResult
from app.services.face_detector import FaceDetection
from app.services.liveness import BlinkTracker, ear


class LivenessServiceTests(unittest.TestCase):
    def test_ear_manual_coordinates(self):
        # 1. Wide open eye: width=6.0, height1=6.0, height2=6.0 -> EAR = 1.0
        open_eye = [
            (0.0, 0.0),    # p1 (corner)
            (2.0, 3.0),    # p2 (top)
            (4.0, 3.0),    # p3 (top)
            (6.0, 0.0),    # p4 (corner)
            (4.0, -3.0),   # p5 (bottom)
            (2.0, -3.0),   # p6 (bottom)
        ]
        self.assertAlmostEqual(ear(open_eye), 1.0, places=4)

        # 2. Closed eye: width=6.0, height1=0.6, height2=0.6 -> EAR = 0.1
        closed_eye = [
            (0.0, 0.0),
            (2.0, 0.3),
            (4.0, 0.3),
            (6.0, 0.0),
            (4.0, -0.3),
            (2.0, -0.3),
        ]
        self.assertAlmostEqual(ear(closed_eye), 0.10, places=4)

        # 3. Degenerate zero-width eye
        degenerate = [(0.0, 0.0)] * 6
        self.assertEqual(ear(degenerate), 0.0)

        # 4. Invalid length raises ValueError
        with self.assertRaises(ValueError):
            ear([(0.0, 0.0)] * 5)

    def test_synthetic_series_always_open_no_blink(self):
        tracker = BlinkTracker()
        device_id = "cam_test"
        center = (200.0, 150.0)
        frame_width = 400

        # Feed steady open eyes for 1.5 seconds (0.1s steps)
        for i in range(15):
            t = 100.0 + i * 0.1
            blink_occurred = tracker.update(device_id, 0.30, center, frame_width, now=t)
            self.assertFalse(blink_occurred)

        self.assertFalse(tracker.has_recent_blink(device_id, within=5.0, now=101.5))

    def test_synthetic_series_open_closed_open_detects_blink(self):
        tracker = BlinkTracker()
        device_id = "cam_test"
        center = (200.0, 150.0)
        frame_width = 400

        # Baseline open eyes
        tracker.update(device_id, 0.30, center, frame_width, now=100.0)
        tracker.update(device_id, 0.30, center, frame_width, now=100.1)

        # Eyes close for 0.2s (t=100.2, t=100.3)
        self.assertFalse(tracker.update(device_id, 0.10, center, frame_width, now=100.2))
        self.assertFalse(tracker.update(device_id, 0.10, center, frame_width, now=100.3))

        # Eyes open again at t=100.4 (total duration 0.2s <= 0.8s) -> Blink triggered!
        blink_detected = tracker.update(device_id, 0.30, center, frame_width, now=100.4)
        self.assertTrue(blink_detected)
        self.assertTrue(
            tracker.has_recent_blink(
                device_id, within=5.0, near_center=center, frame_width=frame_width, now=100.4
            )
        )

    def test_synthetic_series_closed_for_2s_not_a_blink(self):
        tracker = BlinkTracker()
        device_id = "cam_test"
        center = (200.0, 150.0)
        frame_width = 400

        # Open eyes at start
        tracker.update(device_id, 0.30, center, frame_width, now=100.0)

        # Closed eyes for 2.0 full seconds (t=100.1 to t=102.1)
        for i in range(21):
            t = 100.1 + i * 0.1
            tracker.update(device_id, 0.08, center, frame_width, now=t)

        # Eyes open at t=102.2 -> closed duration was 2.0s > 0.8s -> NOT a blink
        blink_detected = tracker.update(device_id, 0.30, center, frame_width, now=102.2)
        self.assertFalse(blink_detected)
        self.assertFalse(tracker.has_recent_blink(device_id, within=5.0, now=102.2))

    def test_center_jump_resets_tracker(self):
        tracker = BlinkTracker()
        device_id = "cam_test"
        center = (100.0, 150.0)
        frame_width = 400

        # Successful blink sequence
        tracker.update(device_id, 0.30, center, frame_width, now=100.0)
        tracker.update(device_id, 0.10, center, frame_width, now=100.1)
        tracker.update(device_id, 0.30, center, frame_width, now=100.2)
        self.assertTrue(tracker.has_recent_blink(device_id, within=5.0, now=100.2))

        # Face center suddenly jumps by 160px (> 25% of 400px = 100px)
        new_center = (260.0, 150.0)
        tracker.update(device_id, 0.30, new_center, frame_width, now=100.3)

        # State should be reset, blink invalidated
        self.assertFalse(tracker.has_recent_blink(device_id, within=5.0, now=100.3))

    def test_face_lost_for_over_1s_resets_history(self):
        tracker = BlinkTracker()
        device_id = "cam_test"
        center = (200.0, 150.0)
        frame_width = 400

        tracker.update(device_id, 0.30, center, frame_width, now=100.0)
        state = tracker._get_state(device_id)
        self.assertEqual(len(state.samples), 1)

        # No face detected at t=101.5 (> 1.0s gap)
        tracker.handle_no_face(device_id, now=101.5)
        self.assertEqual(len(state.samples), 0)

    def test_consume_blink(self):
        tracker = BlinkTracker()
        device_id = "cam_test"
        center = (200.0, 150.0)
        frame_width = 400

        tracker.update(device_id, 0.30, center, frame_width, now=100.0)
        tracker.update(device_id, 0.10, center, frame_width, now=100.1)
        tracker.update(device_id, 0.30, center, frame_width, now=100.2)
        self.assertTrue(tracker.has_recent_blink(device_id, within=5.0, now=100.2))

        # Consume blink upon successful attendance
        tracker.consume_blink(device_id)
        self.assertFalse(tracker.has_recent_blink(device_id, within=5.0, now=100.2))

    def test_has_recent_blink_distance_mismatch(self):
        tracker = BlinkTracker()
        device_id = "cam_test"
        center = (100.0, 100.0)
        frame_width = 400

        tracker.update(device_id, 0.30, center, frame_width, now=100.0)
        tracker.update(device_id, 0.10, center, frame_width, now=100.1)
        tracker.update(device_id, 0.30, center, frame_width, now=100.2)

        # Check near same center -> True
        self.assertTrue(
            tracker.has_recent_blink(
                device_id, within=5.0, near_center=(110.0, 105.0), frame_width=400, now=100.2
            )
        )

        # Check near far center (250, 100) -> distance 150 > 100 -> False
        self.assertFalse(
            tracker.has_recent_blink(
                device_id, within=5.0, near_center=(250.0, 100.0), frame_width=400, now=100.2
            )
        )


class LivenessPipelineIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{self.temp.name}/test.db", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(self.engine, expire_on_commit=False)
        app = create_app()

        def db():
            with self.factory() as session:
                yield session

        app.dependency_overrides[get_db] = db
        self.client = TestClient(app)
        token = self.client.post(
            "/api/auth/login", json={"username": "admin", "password": "test-password-only"}
        ).json()["access_token"]
        self.auth = {"Authorization": f"Bearer {token}"}
        self.device = {"X-Device-Token": "test-device-only", "X-Device-ID": "cam"}

        # Seed class, student, session
        self.class_id = self.client.post(
            "/api/classes", headers=self.auth, json={"code": "C1", "name": "Class"}
        ).json()["id"]
        self.student_id = self.client.post(
            "/api/students",
            headers=self.auth,
            json={"student_code": "SV1", "name": "Student", "class_id": self.class_id},
        ).json()["id"]
        self.session_id = self.client.post(
            "/api/sessions", headers=self.auth, json={"class_id": self.class_id, "title": "IoT"}
        ).json()["id"]
        self.client.post(f"/api/sessions/{self.session_id}/start", headers=self.auth, json={})

        # Heartbeat and config device
        self.client.post(
            "/api/devices/heartbeat",
            headers=self.device,
            json={"name": "cam", "ip_address": "127.0.0.1"},
        )
        self.client.put(
            "/api/devices/cam/config",
            headers=self.auth,
            json={"session_id": self.session_id, "roi_left": 0.0, "roi_top": 0.0, "roi_right": 1.0, "roi_bottom": 1.0},
        )

        # Add face reference in DB
        with self.factory() as session:
            ref = FaceReference(
                student_id=self.student_id,
                embedding=str([[0.0] * 128]),
                enrolled_by="admin",
            )
            session.add(ref)
            session.commit()

    def tearDown(self):
        self.temp.cleanup()

    def frame(self, body=None):
        if body is None:
            import cv2
            import numpy as np
            body = cv2.imencode(".jpg", np.zeros((160, 160, 3), dtype=np.uint8))[1].tobytes()
        return self.client.post(
            f"/api/devices/cam/frames?session_id={self.session_id}",
            headers=self.device,
            files={"image": ("frame.jpg", body, "image/jpeg")},
        )

    def test_pipeline_gate_rejects_when_blink_not_detected(self):
        detection = FaceDetection((40, 40, 80, 80), (80, 80), 6400, (160, 160), True, 1)
        mock_tracker = MagicMock()
        mock_tracker.is_available.return_value = True
        mock_tracker.has_recent_blink.return_value = False

        with patch("app.api.attendance._detector") as detector, \
             patch("app.api.attendance._pad") as pad, \
             patch("app.api.attendance._recognizer") as recognizer, \
             patch("app.api.attendance._liveness", return_value=mock_tracker):
            detector.return_value.detect_largest.return_value = (detection, "ok")
            pad.return_value.evaluate.return_value = PadResult(True, "passed", 0.99)
            recognizer.return_value.ready = True
            recognizer.return_value.encode.return_value = np.zeros(128, dtype=np.float64)

            # Stability warmup 2 frames
            self.frame()
            self.frame()
            # 3rd frame reaches liveness check: rejected!
            res = self.frame().json()
            self.assertFalse(res["accepted"])
            self.assertEqual(res["reason"], "liveness: blink required")

    def test_pipeline_gate_accepts_when_blink_detected_and_consumes(self):
        detection = FaceDetection((40, 40, 80, 80), (80, 80), 6400, (160, 160), True, 1)
        mock_tracker = MagicMock()
        mock_tracker.is_available.return_value = True
        mock_tracker.has_recent_blink.return_value = True

        with patch("app.api.attendance._detector") as detector, \
             patch("app.api.attendance._pad") as pad, \
             patch("app.api.attendance._recognizer") as recognizer, \
             patch("app.api.attendance._liveness", return_value=mock_tracker):
            detector.return_value.detect_largest.return_value = (detection, "ok")
            pad.return_value.evaluate.return_value = PadResult(True, "passed", 0.99)
            recognizer.return_value.ready = True
            recognizer.return_value.encode.return_value = np.zeros(128, dtype=np.float64)

            self.frame()
            self.frame()
            res = self.frame().json()
            self.assertTrue(res["accepted"])
            self.assertTrue(res["created"])
            mock_tracker.consume_blink.assert_called_with("cam")

    def test_pipeline_gate_unavailable_fails_closed(self):
        detection = FaceDetection((40, 40, 80, 80), (80, 80), 6400, (160, 160), True, 1)
        mock_tracker = MagicMock()
        mock_tracker.is_available.return_value = False

        with patch("app.api.attendance._detector") as detector, \
             patch("app.api.attendance._pad") as pad, \
             patch("app.api.attendance._recognizer") as recognizer, \
             patch("app.api.attendance._liveness", return_value=mock_tracker):
            detector.return_value.detect_largest.return_value = (detection, "ok")
            pad.return_value.evaluate.return_value = PadResult(True, "passed", 0.99)
            recognizer.return_value.ready = True

            self.frame()
            self.frame()
            res = self.frame().json()
            self.assertFalse(res["accepted"])
            self.assertEqual(res["reason"], "liveness unavailable")
