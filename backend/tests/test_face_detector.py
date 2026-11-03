"""Tests for FaceDetector (YuNet + Haar fallback) and box clamping."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from app.core.config import settings
from app.services.face_detector import FaceDetection, FaceDetector, clamp_box
from app.services.stability import StabilityGate


class FaceDetectorTests(unittest.TestCase):
    def test_invalid_input_frames(self):
        detector = FaceDetector()
        res, reason = detector.detect_largest(None)
        self.assertIsNone(res)
        self.assertEqual(reason, "invalid image")

        res, reason = detector.detect_largest("not_an_array")  # type: ignore[arg-type]
        self.assertIsNone(res)
        self.assertEqual(reason, "invalid image")

        small_frame = np.zeros((32, 32, 3), dtype=np.uint8)
        res, reason = detector.detect_largest(small_frame)
        self.assertIsNone(res)
        self.assertEqual(reason, "image is too small")

    def test_clamp_box_bounds(self):
        # Negative coords
        box = clamp_box((-20.0, -10.0, 100.0, 100.0), width=200, height=200)
        self.assertEqual(box, (0, 0, 80, 90))
        self.assertGreaterEqual(box[0], 0)
        self.assertGreaterEqual(box[1], 0)
        self.assertLessEqual(box[0] + box[2], 200)
        self.assertLessEqual(box[1] + box[3], 200)

        # Exceeding right and bottom
        box = clamp_box((150.0, 160.0, 100.0, 80.0), width=200, height=200)
        self.assertEqual(box, (150, 160, 50, 40))
        self.assertLessEqual(box[0] + box[2], 200)
        self.assertLessEqual(box[1] + box[3], 200)

        # Fully within image
        box = clamp_box((30.0, 40.0, 60.0, 70.0), width=200, height=200)
        self.assertEqual(box, (30, 40, 60, 70))

    def test_no_face_detected_on_blank_frame(self):
        detector = FaceDetector()
        blank = np.zeros((160, 160, 3), dtype=np.uint8)
        res, reason = detector.detect_largest(blank)
        self.assertIsNone(res)
        self.assertEqual(reason, "no face detected")

    def test_fallback_when_model_missing(self):
        with self.assertLogs("app.services.face_detector", level="WARNING") as logs:
            detector = FaceDetector(
                detector_type="yunet",
                model_path="models/yunet/does_not_exist_xyz.onnx",
            )
        self.assertTrue(detector.using_fallback)
        self.assertTrue(any("Falling back to Haar cascade" in msg for msg in logs.output))
        # Detector still functions via Haar cascade
        blank = np.zeros((160, 160, 3), dtype=np.uint8)
        res, reason = detector.detect_largest(blank)
        self.assertIsNone(res)
        self.assertEqual(reason, "no face detected")

    def test_fallback_when_yunet_create_raises(self):
        with patch("cv2.FaceDetectorYN.create", side_effect=RuntimeError("DNN mock load error")):
            with self.assertLogs("app.services.face_detector", level="WARNING") as logs:
                detector = FaceDetector(detector_type="yunet")
            self.assertTrue(detector.using_fallback)
            self.assertTrue(any("Falling back to Haar cascade" in msg for msg in logs.output))

    def test_haar_detector_mode(self):
        detector = FaceDetector(detector_type="haar")
        self.assertFalse(detector.using_fallback)
        blank = np.zeros((160, 160, 3), dtype=np.uint8)
        res, reason = detector.detect_largest(blank)
        self.assertIsNone(res)
        self.assertEqual(reason, "no face detected")

    def test_yunet_detection_parsing_and_landmarks(self):
        detector = FaceDetector(detector_type="yunet")
        if detector.using_fallback:
            self.skipTest("YuNet model not available")

        # Mock the underlying _yunet instance to return a controlled face output
        mock_face = np.array([
            [
                50.0, 50.0, 60.0, 60.0,  # x, y, w, h
                65.0, 70.0,               # right eye
                95.0, 70.0,               # left eye
                80.0, 85.0,               # nose
                70.0, 95.0,               # right mouth
                90.0, 95.0,               # left mouth
                0.95,                     # score
            ]
        ], dtype=np.float32)

        # High variance synthetic pattern inside face box
        frame = np.full((160, 160, 3), 128, dtype=np.uint8)
        frame[50:110, 50:110] = np.random.randint(0, 255, (60, 60, 3), dtype=np.uint8)

        mock_yunet = MagicMock()
        mock_yunet.detect.return_value = (1, mock_face)
        detector._yunet = mock_yunet

        det, reason = detector.detect_largest(frame)
        self.assertIsNotNone(det)
        self.assertEqual(reason, "ok")
        self.assertEqual(det.box, (50, 50, 60, 60))
        self.assertIsNotNone(det.landmarks5)
        self.assertEqual(len(det.landmarks5), 5)
        self.assertAlmostEqual(det.landmarks5[0][0], 65.0, places=2)
        self.assertAlmostEqual(det.landmarks5[0][1], 70.0, places=2)
        self.assertAlmostEqual(det.landmarks5[2][0], 80.0, places=2)  # nose

    def test_multiple_faces_in_roi(self):
        detector = FaceDetector(detector_type="yunet")
        if detector.using_fallback:
            self.skipTest("YuNet model not available")

        # Two faces both in ROI
        mock_faces = np.array([
            [40.0, 40.0, 40.0, 40.0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.9],
            [90.0, 40.0, 40.0, 40.0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.9],
        ], dtype=np.float32)
        frame = np.zeros((160, 160, 3), dtype=np.uint8)

        mock_yunet = MagicMock()
        mock_yunet.detect.return_value = (1, mock_faces)
        detector._yunet = mock_yunet

        det, reason = detector.detect_largest(frame)
        self.assertIsNone(det)
        self.assertEqual(reason, "multiple faces in ROI")

    def test_face_outside_roi(self):
        detector = FaceDetector(detector_type="yunet")
        if detector.using_fallback:
            self.skipTest("YuNet model not available")

        # Face far at the top-left outside default ROI (0.22, 0.15, 0.78, 0.85)
        mock_faces = np.array([
            [2.0, 2.0, 20.0, 20.0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.9],
        ], dtype=np.float32)
        frame = np.zeros((200, 200, 3), dtype=np.uint8)

        mock_yunet = MagicMock()
        mock_yunet.detect.return_value = (1, mock_faces)
        detector._yunet = mock_yunet

        det, reason = detector.detect_largest(frame)
        self.assertIsNone(det)
        self.assertEqual(reason, "face outside ROI")

    def test_stability_gate_continuity_across_frames(self):
        gate = StabilityGate()
        device_id = "cam_01"
        box = (60, 60, 80, 80)
        t0 = 1000.0

        # Frame 1: count = 1 -> False
        self.assertFalse(gate.observe(device_id, box, now=t0))

        # Frame 2: same box, within stable_gap_seconds -> count = 2 -> False
        self.assertFalse(gate.observe(device_id, box, now=t0 + 0.3))

        # Frame 3: count = 3 >= 3 -> True (stable)
        self.assertTrue(gate.observe(device_id, box, now=t0 + 0.6))

        # Box suddenly moves far away -> reset count to 1 -> False
        new_box = (150, 150, 80, 80)
        self.assertFalse(gate.observe(device_id, new_box, now=t0 + 0.9))

    def test_stability_gate_end_to_end_with_detector(self):
        """Simulate 3 consecutive detections on the same image passing into StabilityGate."""
        detector = FaceDetector(detector_type="yunet")
        if detector.using_fallback:
            self.skipTest("YuNet model not available")

        mock_face = np.array([
            [
                50.0, 50.0, 60.0, 60.0,
                65.0, 70.0, 95.0, 70.0, 80.0, 85.0, 70.0, 95.0, 90.0, 95.0,
                0.95,
            ]
        ], dtype=np.float32)

        frame = np.full((160, 160, 3), 128, dtype=np.uint8)
        frame[50:110, 50:110] = np.random.randint(0, 255, (60, 60, 3), dtype=np.uint8)

        mock_yunet = MagicMock()
        mock_yunet.detect.return_value = (1, mock_face)
        detector._yunet = mock_yunet

        gate = StabilityGate()
        device_id = "camera_esp32_01"

        # 3 consecutive detections of the same image
        observations = []
        for i in range(3):
            det, reason = detector.detect_largest(frame)
            self.assertIsNotNone(det)
            self.assertEqual(reason, "ok")
            is_stable = gate.observe(device_id, det.box, now=100.0 + i * 0.3)
            observations.append(is_stable)

        # Frame 1 and 2 not yet stable, Frame 3 reached 3 consecutive frames with IoU=1.0 -> True
        self.assertEqual(observations, [False, False, True])

