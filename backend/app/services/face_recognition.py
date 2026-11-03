"""Optional dlib embeddings; stored references come only from consented enrollment."""
from __future__ import annotations

import io
import json
from dataclasses import dataclass

import numpy as np

from app.core.config import settings
from app.models.school import FaceReference, Student


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
    if probe is None or not isinstance(probe, np.ndarray) or probe.shape != (128,) or not np.isfinite(probe).all():
        return None
    thresh = settings.recognition_threshold if threshold is None else threshold
    marg = settings.recognition_margin if margin is None else margin
    matches = []
    for reference, student in rows:
        try:
            vector = np.asarray(json.loads(reference.embedding), dtype=np.float64)
        except (ValueError, TypeError):
            continue
        if vector.shape != (128,) or not np.isfinite(vector).all():
            continue
        dist = float(np.linalg.norm(vector - probe))
        if not np.isfinite(dist):
            continue
        matches.append((dist, student.student_code))
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

    def encode(self, image_bytes: bytes, box=None):
        if self.engine is None:
            raise ValueError(self.reason)
        image = self.engine.load_image_file(io.BytesIO(image_bytes))
        if box is None:
            locations = self.engine.face_locations(image)
            if len(locations) == 0:
                raise ValueError("Không tìm thấy khuôn mặt trong ảnh. Vui lòng nhìn thẳng và đủ sáng.")
            if len(locations) > 1:
                raise ValueError(f"Phát hiện {len(locations)} khuôn mặt. Yêu cầu chỉ có 1 người trong khung hình.")
        else:
            x, y, w, h = box
            locations = [(y, x + w, y + h, x)]
        encodings = self.engine.face_encodings(image, locations)
        if len(encodings) != 1 or not np.isfinite(encodings[0]).all():
            raise ValueError("Không thể trích xuất đặc trưng khuôn mặt từ ảnh.")
        return encodings[0]
