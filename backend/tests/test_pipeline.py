import json
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from app.api.attendance import last_frames
from app.services.antispoof import AntiSpoofAdapter, _get_new_box, prepare_face
from app.services.face_recognition import RecognitionResult, match
from app.services.stability import StabilityGate
from app.services.reporting import attendance_csv


class PipelineTests(unittest.TestCase):
    def test_preprocessing_is_bgr_unnormalized(self):
        image = np.full((160, 160, 3), (10, 50, 200), dtype=np.uint8)
        tensor = prepare_face(image, (40, 40, 80, 80))
        self.assertEqual(tensor.shape, (1, 3, 80, 80))
        self.assertEqual(tensor.dtype, np.float32)
        self.assertEqual(float(tensor[0, 0, 0, 0]), 10)
        self.assertEqual(float(tensor[0, 2, 0, 0]), 200)

    def test_invalid_face_box(self):
        frame = np.zeros((80, 80, 3), dtype=np.uint8)
        with self.assertRaises(ValueError):
            prepare_face(frame, (0, 0, 0, 10))

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
        dummy = np.zeros((80, 80, 3), dtype=np.uint8)
        self.assertFalse(adapter.evaluate(dummy, (1, 1, 1, 1)).is_real)
        from unittest.mock import Mock
        adapter.session = Mock()
        adapter.input_name, adapter.output_name = "input", "output"
        adapter.session.run.return_value = [np.array([[np.nan, 0, 0]])]
        with patch("app.services.antispoof.prepare_face", return_value=np.zeros((1, 3, 80, 80), np.float32)):
            self.assertEqual(adapter.evaluate(dummy, (1, 1, 1, 1)).reason, "invalid PAD output")

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

    def test_match_multi_sample_reference(self):
        probe = np.zeros(128, dtype=np.float64)
        # Sinh viên SV1 có 3 mẫu: mẫu 1 cách 0.55, mẫu 2 cách 0.35, mẫu 3 cách 0.60
        vec1 = [0.55] + [0.0] * 127
        vec2 = [0.35] + [0.0] * 127
        vec3 = [0.60] + [0.0] * 127
        ref_multi = SimpleNamespace(embedding=json.dumps([vec1, vec2, vec3]))
        stu1 = SimpleNamespace(student_code="SV1")

        # Phải lấy min_dist = 0.35
        res = match(probe, [(ref_multi, stu1)], threshold=0.50, margin=0.05)
        self.assertIsNotNone(res)
        self.assertEqual(res.student_code, "SV1")
        self.assertAlmostEqual(res.distance, 0.35, places=5)

    def test_match_legacy_1d_and_warning(self):
        probe = np.zeros(128, dtype=np.float64)
        # Vector 128 số có norm = 1.0 (chuẩn hóa L2 cũ)
        vec_l2 = [1.0] + [0.0] * 127
        ref_legacy = SimpleNamespace(embedding=json.dumps(vec_l2))
        stu = SimpleNamespace(student_code="SV_LEGACY")

        with self.assertLogs("app.services.face_recognition", level="WARNING") as cm:
            res = match(probe, [(ref_legacy, stu)], threshold=1.5, margin=0.05)
            self.assertIsNotNone(res)
            self.assertEqual(res.student_code, "SV_LEGACY")
            self.assertTrue(any("embedding cu da chuan hoa L2, nen dang ky lai" in msg for msg in cm.output))

    def test_margin_between_different_students_not_within_same_student(self):
        probe = np.zeros(128, dtype=np.float64)
        # SV1 có 2 mẫu: mẫu A cách 0.40, mẫu B cách 0.42
        vec_sv1_a = [0.40] + [0.0] * 127
        vec_sv1_b = [0.42] + [0.0] * 127
        ref_sv1 = SimpleNamespace(embedding=json.dumps([vec_sv1_a, vec_sv1_b]))
        stu1 = SimpleNamespace(student_code="SV1")

        # Nếu chỉ có SV1: không được vi phạm margin vì 0.40 và 0.42 là cùng 1 người!
        res = match(probe, [(ref_sv1, stu1)], threshold=0.50, margin=0.05)
        self.assertIsNotNone(res)
        self.assertEqual(res.student_code, "SV1")
        self.assertAlmostEqual(res.distance, 0.40, places=5)

        # Bây giờ thêm SV2 có mẫu cách 0.43 (khác sinh viên)
        vec_sv2 = [0.43] + [0.0] * 127
        ref_sv2 = SimpleNamespace(embedding=json.dumps([vec_sv2]))
        stu2 = SimpleNamespace(student_code="SV2")

        # Giữa SV1 (0.40) và SV2 (0.43): chênh lệch 0.03 < margin 0.05 -> Ambiguous -> None!
        res_ambiguous = match(probe, [(ref_sv1, stu1), (ref_sv2, stu2)], threshold=0.50, margin=0.05)
        self.assertIsNone(res_ambiguous)

    def test_detector_accepts_ndarray(self):
        from app.services.face_detector import FaceDetector
        detector = FaceDetector()
        frame = np.zeros((160, 160, 3), dtype=np.uint8)
        det, reason = detector.detect_largest(frame, (0.0, 0.0, 1.0, 1.0))
        self.assertIsNone(det)
        self.assertEqual(reason, "no face detected")

    def test_decode_image_and_dimension_validation(self):
        from app.services.images import decode_image
        tiny = np.zeros((32, 32, 3), dtype=np.uint8)
        _, tiny_png = cv2.imencode(".png", tiny)
        with self.assertRaises(ValueError):
            decode_image(tiny_png.tobytes())

        valid = np.zeros((80, 80, 3), dtype=np.uint8)
        _, valid_png = cv2.imencode(".png", valid)
        decoded = decode_image(valid_png.tobytes())
        self.assertEqual(decoded.shape, (80, 80, 3))

    def test_decode_image_rejects_oversized_header_without_calling_imdecode(self):
        import io
        from PIL import Image
        from app.services.images import decode_image

        buf = io.BytesIO()
        Image.new("RGB", (5000, 5000), color="white").save(buf, format="PNG")
        oversized = buf.getvalue()

        with patch("cv2.imdecode", side_effect=AssertionError("cv2.imdecode must not be called")):
            with self.assertRaises(ValueError) as ctx:
                decode_image(oversized)
            self.assertIn("at most 4 megapixels", str(ctx.exception))

    def test_decode_image_rejects_gif_format(self):
        import io
        from PIL import Image
        from app.services.images import decode_image

        buf = io.BytesIO()
        Image.new("RGB", (80, 80), color="white").save(buf, format="GIF")
        gif_bytes = buf.getvalue()

        with self.assertRaises(ValueError) as ctx:
            decode_image(gif_bytes)
        self.assertIn("Only JPEG and PNG images are accepted", str(ctx.exception))

    def test_get_new_box_shifts_instead_of_truncating(self):
        # Image 400x300, face box at left boundary x=10, y=100, w=80, h=100
        # Scale 2.7 -> new_w = 80 * 2.7 = 216, new_h = 100 * 2.7 = 270
        # Center x = 10 + 40 = 50. Left = 50 - 108 = -58 (< 0).
        # Minivision shifts box to right so left=0, right = 158 - (-58) = 216.
        left, top, right, bottom = _get_new_box(400, 300, (10, 100, 80, 100), scale=2.7)
        self.assertEqual(left, 0)
        self.assertEqual(right, 216)
        self.assertEqual(right - left, 216)  # Full width preserved!
        self.assertGreaterEqual(top, 0)
        self.assertLessEqual(bottom, 299)

        # Right boundary: x=310, y=100, w=80, h=100 in 400x300
        # Center x = 350. Right = 350 + 108 = 458 (> 399).
        # Box is shifted left to keep right = 399.
        left_r, top_r, right_r, bottom_r = _get_new_box(400, 300, (310, 100, 80, 100), scale=2.7)
        self.assertEqual(right_r, 399)
        self.assertEqual(right_r - left_r, 216)  # Full width preserved!
        self.assertGreaterEqual(left_r, 0)

        # Top boundary: y=5, x=100, w=80, h=80 in 400x300
        # Center y = 45. Top = 45 - 108 = -63 (< 0).
        # Box is shifted down so top = 0.
        left_t, top_t, right_t, bottom_t = _get_new_box(400, 300, (100, 5, 80, 80), scale=2.7)
        self.assertEqual(top_t, 0)
        self.assertEqual(bottom_t, 216)
        self.assertEqual(bottom_t - top_t, 216)  # Full height preserved!

    def test_pad_consecutive_frames_requirement(self):
        from unittest.mock import MagicMock
        adapter = AntiSpoofAdapter.__new__(AntiSpoofAdapter)
        adapter._consecutive_counts = {}
        adapter.session = MagicMock()
        adapter.input_name = "input"
        adapter.output_name = "output"
        # Logits that result in class 1 (Real) with high probability
        adapter.session.run.return_value = [np.array([[0.0, 10.0, 0.0]], dtype=np.float32)]

        dummy_frame = np.full((160, 160, 3), 128, dtype=np.uint8)
        box = (40, 40, 80, 80)

        mock_settings = SimpleNamespace(
            pad_calibrated=True,
            pad_real_threshold=0.45,
            pad_crop_scale=2.7,
            pad_min_consecutive=2,
        )

        with patch("app.services.antispoof.settings", mock_settings):
            # Frame 1: Real frame, but consecutive count = 1 < 2 -> is_real is False
            res1 = adapter.evaluate(dummy_frame, box, device_id="cam_01")
            self.assertFalse(res1.is_real)
            self.assertGreater(res1.score, 0.99)

            # Frame 2: Real frame, consecutive count = 2 >= 2 -> is_real is True
            res2 = adapter.evaluate(dummy_frame, box, device_id="cam_01")
            self.assertTrue(res2.is_real)

            # Reset device -> consecutive count resets
            adapter.reset_device("cam_01")
            res3 = adapter.evaluate(dummy_frame, box, device_id="cam_01")
            self.assertFalse(res3.is_real)


if __name__ == "__main__":
    unittest.main()
