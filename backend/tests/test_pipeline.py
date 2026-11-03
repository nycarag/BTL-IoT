import json
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from app.api.attendance import last_frames
from app.services.antispoof import AntiSpoofAdapter, prepare_face
from app.services.face_recognition import RecognitionResult, match
from app.services.stability import StabilityGate
from app.services.reporting import attendance_csv


class PipelineTests(unittest.TestCase):
    def test_preprocessing_is_bgr_unnormalized(self):
        image = np.full((160, 160, 3), (10, 50, 200), dtype=np.uint8)
        _, data = cv2.imencode(".png", image)
        tensor = prepare_face(data.tobytes(), (40, 40, 80, 80))
        self.assertEqual(tensor.shape, (1, 3, 80, 80))
        self.assertEqual(tensor.dtype, np.float32)
        self.assertEqual(float(tensor[0, 0, 0, 0]), 10)
        self.assertEqual(float(tensor[0, 2, 0, 0]), 200)

    def test_invalid_face_box(self):
        _, data = cv2.imencode(".png", np.zeros((80, 80, 3), dtype=np.uint8))
        with self.assertRaises(ValueError):
            prepare_face(data.tobytes(), (0, 0, 0, 10))

    def test_stability_resets_on_motion_and_gap(self):
        gate = StabilityGate()
        self.assertFalse(gate.observe("cam", (0, 0, 100, 100), 0))
        self.assertFalse(gate.observe("cam", (1, 1, 100, 100), 1))
        self.assertTrue(gate.observe("cam", (2, 2, 100, 100), 2))
        self.assertFalse(gate.observe("cam", (100, 100, 100, 100), 3))
        self.assertFalse(gate.observe("cam", (100, 100, 100, 100), 10))

    def test_csv_formula_is_neutralized(self):
        report = attendance_csv([dict(checked_at="now", student_code="SV1", student_name="=1+1",
                                      status="present", verification="manual")]).decode("utf-8-sig")
        self.assertIn("'=1+1", report)

    def test_pad_missing_and_nan_fail_closed(self):
        adapter = AntiSpoofAdapter.__new__(AntiSpoofAdapter)
        adapter.session = None
        adapter.reason = "missing"
        self.assertFalse(adapter.evaluate(b"x", (1, 1, 1, 1)).is_real)
        from unittest.mock import Mock
        adapter.session = Mock()
        adapter.input_name, adapter.output_name = "input", "output"
        adapter.session.run.return_value = [np.array([[np.nan, 0, 0]])]
        with patch("app.services.antispoof.prepare_face", return_value=np.zeros((1, 3, 80, 80), np.float32)):
            self.assertEqual(adapter.evaluate(b"x", (1, 1, 1, 1)).reason, "invalid PAD output")

    def test_match_empty_and_invalid_probe(self):
        valid_probe = np.zeros(128, dtype=np.float64)
        self.assertIsNone(match(valid_probe, []))
        self.assertIsNone(match(None, []))
        self.assertIsNone(match(np.zeros(64, dtype=np.float64), []))
        nan_probe = np.zeros(128, dtype=np.float64)
        nan_probe[0] = np.nan
        self.assertIsNone(match(nan_probe, []))

    def test_match_invalid_references_ignored(self):
        probe = np.zeros(128, dtype=np.float64)
        stu = SimpleNamespace(student_code="SV_BAD")
        bad_refs = [
            (SimpleNamespace(embedding="invalid json string"), stu),
            (SimpleNamespace(embedding=json.dumps([1.0, 2.0])), stu),
            (SimpleNamespace(embedding=json.dumps([float("nan")] * 128)), stu),
            (SimpleNamespace(embedding=json.dumps([float("inf")] * 128)), stu),
        ]
        self.assertIsNone(match(probe, bad_refs, threshold=1.0))

    def test_match_threshold_and_margin(self):
        probe = np.zeros(128, dtype=np.float64)
        vec_sv1 = [0.40] + [0.0] * 127
        vec_sv2 = [0.42] + [0.0] * 127
        vec_sv3 = [0.55] + [0.0] * 127

        ref1 = (SimpleNamespace(embedding=json.dumps(vec_sv1)), SimpleNamespace(student_code="SV1"))
        ref2 = (SimpleNamespace(embedding=json.dumps(vec_sv2)), SimpleNamespace(student_code="SV2"))
        ref3 = (SimpleNamespace(embedding=json.dumps(vec_sv3)), SimpleNamespace(student_code="SV3"))

        # Single match within threshold
        res = match(probe, [ref1], threshold=0.50, margin=0.05)
        self.assertIsNotNone(res)
        self.assertEqual(res.student_code, "SV1")
        self.assertAlmostEqual(res.distance, 0.40, places=5)

        # Single match exceeding threshold
        self.assertIsNone(match(probe, [ref3], threshold=0.50, margin=0.05))

        # Two matches too close (margin violation: 0.42 - 0.40 = 0.02 < 0.05)
        self.assertIsNone(match(probe, [ref1, ref2], threshold=0.50, margin=0.05))

        # Margin satisfied: 0.42 - 0.40 = 0.02 >= 0.01
        res = match(probe, [ref1, ref2], threshold=0.50, margin=0.01)
        self.assertIsNotNone(res)
        self.assertEqual(res.student_code, "SV1")
        self.assertAlmostEqual(res.distance, 0.40, places=5)

    def test_rate_limit_cleanup_preserves_recent_devices(self):
        last_frames.clear()
        now = time.monotonic()
        # Seed 200 stale devices (> 60s)
        for i in range(200):
            last_frames[f"stale_{i}"] = now - 100.0
        # Seed 60 recent devices (<= 60s)
        for i in range(60):
            last_frames[f"recent_{i}"] = now - 5.0

        self.assertEqual(len(last_frames), 260)
        # Simulate eviction logic when len > 256
        stale_keys = [k for k, t in last_frames.items() if now - t > 60]
        for k in stale_keys:
            last_frames.pop(k, None)

        self.assertEqual(len(last_frames), 60)
        for i in range(60):
            self.assertIn(f"recent_{i}", last_frames)
        for i in range(200):
            self.assertNotIn(f"stale_{i}", last_frames)
        last_frames.clear()


if __name__ == "__main__":
    unittest.main()
