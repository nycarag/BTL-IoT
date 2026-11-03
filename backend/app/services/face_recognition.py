"""Optional dlib embeddings; stored references come only from consented enrollment."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import cv2
import numpy as np

from app.core.config import settings
from app.models.school import FaceReference, Student

logger = logging.getLogger(__name__)

_warned_l2_legacy = False


@dataclass(frozen=True)
class RecognitionResult:
    student_code: str
    distance: float


def match(
    probe: np.ndarray,
    rows: list[tuple[FaceReference, Student]],
    threshold: float | None = None,
    margin: float | None = None,
) -> RecognitionResult | None:
    global _warned_l2_legacy
    if probe is None or not isinstance(probe, np.ndarray) or probe.shape != (128,) or not np.isfinite(probe).all():
        return None
    thresh = settings.recognition_threshold if threshold is None else threshold
    marg = settings.recognition_margin if margin is None else margin
    matches: list[tuple[float, str]] = []

    for reference, student in rows:
        try:
            data = json.loads(reference.embedding)
            arr = np.asarray(data, dtype=np.float64)
        except (ValueError, TypeError):
            continue

        if arr.ndim == 1:
            if arr.shape != (128,):
                continue
            norm_val = float(np.linalg.norm(arr))
            if abs(norm_val - 1.0) < 1e-3:
                if not _warned_l2_legacy:
                    logger.warning("embedding cu da chuan hoa L2, nen dang ky lai")
                    _warned_l2_legacy = True
            arr = arr.reshape(1, 128)
        elif arr.ndim == 2:
            if arr.shape[1] != 128 or arr.shape[0] == 0:
                continue
        else:
            continue

        if not np.isfinite(arr).all():
            continue

        # Khoảng cách Euclid vector hóa giữa probe và tất cả mẫu của sinh viên này
        diffs = arr - probe
        distances = np.linalg.norm(diffs, axis=1)
        min_dist = float(np.min(distances))
        if not np.isfinite(min_dist):
            continue
        matches.append((min_dist, student.student_code))

    matches.sort(key=lambda m: m[0])
    if not matches or matches[0][0] > thresh:
        return None
    if len(matches) > 1 and matches[1][0] - matches[0][0] < marg:
        return None
    return RecognitionResult(matches[0][1], matches[0][0])


class FaceRecognitionAdapter:
    def __init__(self):
        self.engine = None
        self.reason = "Install requirements-recognition.txt to enable face embeddings"
        try:
            import face_recognition
            self.engine = face_recognition
            self.reason = "ready" if settings.recognition_calibrated else "Recognition threshold needs calibration"
        except ImportError:
            pass

    @property
    def ready(self):
        return self.engine is not None and settings.recognition_calibrated

    def encode(self, frame: np.ndarray | bytes, box=None):
        if self.engine is None:
            raise ValueError(self.reason)
        if isinstance(frame, bytes):
            from app.services.images import decode_image
            frame = decode_image(frame)
        elif not isinstance(frame, np.ndarray) or frame.ndim != 3:
            raise ValueError("Invalid image")

        rgb_image = np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), dtype=np.uint8)
        if box is None:
            locations = self.engine.face_locations(rgb_image)
            if len(locations) == 0:
                raise ValueError("Không tìm thấy khuôn mặt trong ảnh. Vui lòng nhìn thẳng và đủ sáng.")
            if len(locations) > 1:
                raise ValueError(f"Phát hiện {len(locations)} khuôn mặt. Yêu cầu chỉ có 1 người trong khung hình.")
        else:
            x, y, w, h = box
            locations = [(y, x + w, y + h, x)]
        encodings = self.engine.face_encodings(rgb_image, locations)
        if len(encodings) != 1 or not np.isfinite(encodings[0]).all():
            raise ValueError("Không thể trích xuất đặc trưng khuôn mặt từ ảnh.")
        return encodings[0]
