"""OpenCV face detection and ROI/quality checks using YuNet with Haar cascade fallback."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import cv2
import numpy as np

from app.core.config import settings
from app.core.domain import inside_roi

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FaceDetection:
    box: tuple[int, int, int, int]
    center: tuple[float, float]
    area: int
    frame_size: tuple[int, int]
    roi_inside: bool
    quality_score: float
    landmarks5: tuple[tuple[float, float], ...] | None = None


def clamp_box(
    raw_box: tuple[float, float, float, float], width: int, height: int
) -> tuple[int, int, int, int]:
    """Clamp a bounding box to keep it within image bounds."""
    rx, ry, rw, rh = raw_box
    x1 = max(0, min(int(round(rx)), width - 1))
    y1 = max(0, min(int(round(ry)), height - 1))
    x2 = max(x1 + 1, min(int(round(rx + rw)), width))
    y2 = max(y1 + 1, min(int(round(ry + rh)), height))
    return x1, y1, x2 - x1, y2 - y1


class FaceDetector:
    def __init__(
        self,
        detector_type: str | None = None,
        model_path: str | None = None,
        score_threshold: float | None = None,
    ) -> None:
        self.detector_type = (detector_type or settings.face_detector).lower().strip()
        self.model_path = model_path or settings.yunet_model_path
        self.score_threshold = (
            score_threshold if score_threshold is not None else settings.face_score_threshold
        )
        self.nms_threshold = 0.3
        self.cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self._cascade: cv2.CascadeClassifier | None = None
        self._yunet: cv2.FaceDetectorYN | None = None
        self.using_fallback: bool = False

        self._init_detector()

    def _init_detector(self) -> None:
        if self.detector_type == "yunet":
            if not os.path.exists(self.model_path):
                logger.warning(
                    "YuNet model file not found at '%s'. Falling back to Haar cascade.",
                    self.model_path,
                )
                self.using_fallback = True
                self._cascade = cv2.CascadeClassifier(self.cascade_path)
            else:
                try:
                    self._yunet = cv2.FaceDetectorYN.create(
                        self.model_path,
                        "",
                        (320, 320),
                        score_threshold=self.score_threshold,
                        nms_threshold=self.nms_threshold,
                    )
                    self.using_fallback = False
                except Exception as exc:
                    logger.warning(
                        "Failed to load YuNet model from '%s' (%s). Falling back to Haar cascade.",
                        self.model_path,
                        exc,
                    )
                    self.using_fallback = True
                    self._cascade = cv2.CascadeClassifier(self.cascade_path)
        else:
            self.using_fallback = False
            self._cascade = cv2.CascadeClassifier(self.cascade_path)

    @property
    def cascade(self) -> cv2.CascadeClassifier:
        if self._cascade is None:
            self._cascade = cv2.CascadeClassifier(self.cascade_path)
        return self._cascade

    def detect_largest(
        self,
        frame: np.ndarray,
        roi: tuple[float, float, float, float] = (0.22, 0.15, 0.78, 0.85),
    ) -> tuple[FaceDetection | None, str]:
        if frame is None or not isinstance(frame, np.ndarray) or frame.ndim != 3:
            return None, "invalid image"

        height, width = frame.shape[:2]
        if width < 64 or height < 64:
            return None, "image is too small"

        gray: np.ndarray | None = None

        if self.detector_type == "yunet" and not self.using_fallback and self._yunet is not None:
            self._yunet.setInputSize((width, height))
            _, raw_faces = self._yunet.detect(frame)
            if raw_faces is None or len(raw_faces) == 0:
                return None, "no face detected"

            candidates: list[
                tuple[tuple[int, int, int, int], tuple[float, float], tuple[tuple[float, float], ...]]
            ] = []
            for face_data in raw_faces:
                clamped = clamp_box(
                    (float(face_data[0]), float(face_data[1]), float(face_data[2]), float(face_data[3])),
                    width,
                    height,
                )
                cx = clamped[0] + clamped[2] / 2.0
                cy = clamped[1] + clamped[3] / 2.0
                center = (cx, cy)
                landmarks = (
                    (float(face_data[4]), float(face_data[5])),
                    (float(face_data[6]), float(face_data[7])),
                    (float(face_data[8]), float(face_data[9])),
                    (float(face_data[10]), float(face_data[11])),
                    (float(face_data[12]), float(face_data[13])),
                )
                if inside_roi(center, (width, height), roi):
                    candidates.append((clamped, center, landmarks))

            if len(candidates) > 1:
                return None, "multiple faces in ROI"
            if not candidates:
                return None, "face outside ROI"

            box, center, landmarks5 = candidates[0]
        else:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self.cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(32, 32)
            )
            if len(faces) == 0:
                return None, "no face detected"

            candidates_haar: list[tuple[tuple[int, int, int, int], tuple[float, float]]] = []
            for face in faces:
                clamped = clamp_box(
                    (float(face[0]), float(face[1]), float(face[2]), float(face[3])),
                    width,
                    height,
                )
                cx = clamped[0] + clamped[2] / 2.0
                cy = clamped[1] + clamped[3] / 2.0
                center = (cx, cy)
                if inside_roi(center, (width, height), roi):
                    candidates_haar.append((clamped, center))

            if len(candidates_haar) > 1:
                return None, "multiple faces in ROI"
            if not candidates_haar:
                return None, "face outside ROI"

            box, center = candidates_haar[0]
            landmarks5 = None

        x, y, box_width, box_height = box
        area = int(box_width * box_height)
        if gray is None:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        crop = gray[y : y + box_height, x : x + box_width]
        if crop.size == 0:
            return None, "image too blurry"

        laplacian_variance = float(cv2.Laplacian(crop, cv2.CV_64F).var())
        quality_score = min(1.0, laplacian_variance / 500.0)
        roi_inside = inside_roi(center, (width, height), roi)

        detection = FaceDetection(
            box=box,
            center=center,
            area=area,
            frame_size=(width, height),
            roi_inside=roi_inside,
            quality_score=quality_score,
            landmarks5=landmarks5,
        )

        if area / (width * height) < settings.min_face_area_ratio:
            return detection, "face too small"
        if not detection.roi_inside:
            return detection, "face outside ROI"
        if laplacian_variance < settings.min_sharpness:
            return detection, "image too blurry"
        return detection, "ok"
