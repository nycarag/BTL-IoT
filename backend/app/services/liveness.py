"""Active liveness service: Eye Aspect Ratio (EAR) blink detection on preview stream."""

from __future__ import annotations

import collections
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Sequence

import cv2
import numpy as np

from app.core.config import settings
from app.services.face_detector import FaceDetector

logger = logging.getLogger(__name__)


def ear(eye6pts: Sequence[tuple[float, float]] | np.ndarray) -> float:
    """Compute Eye Aspect Ratio (EAR) from 6 2D eye landmark points.

    EAR = (|p2 - p6| + |p3 - p5|) / (2 * |p1 - p4|)
    Following Soukupová and Čech (2016).
    """
    if len(eye6pts) != 6:
        raise ValueError(f"Expected 6 eye landmark points, got {len(eye6pts)}")

    p1, p2, p3, p4, p5, p6 = eye6pts
    v1 = math.hypot(p2[0] - p6[0], p2[1] - p6[1])
    v2 = math.hypot(p3[0] - p5[0], p3[1] - p5[1])
    h = math.hypot(p1[0] - p4[0], p1[1] - p4[1])
    if h < 1e-6:
        return 0.0
    return (v1 + v2) / (2.0 * h)


@dataclass
class DeviceBlinkState:
    samples: collections.deque[tuple[float, float, tuple[float, float]]] = field(
        default_factory=lambda: collections.deque(maxlen=128)
    )
    last_blink_at: float | None = None
    last_blink_center: tuple[float, float] | None = None
    last_seen: float = 0.0
    last_center: tuple[float, float] | None = None


class BlinkTracker:
    def __init__(self, closed_ratio: float | None = None) -> None:
        self.closed_ratio = closed_ratio
        self._states: dict[str, DeviceBlinkState] = {}
        self.predictor = None
        self.detector = None
        self.available = False

        self._init_models()

    def _init_models(self) -> None:
        try:
            import dlib
            import face_recognition_models

            predictor_path = face_recognition_models.pose_predictor_model_location()
            self.predictor = dlib.shape_predictor(predictor_path)
            self.detector = FaceDetector()
            self.available = True
            logger.info("BlinkTracker initialized with dlib shape_predictor from %s", predictor_path)
        except Exception as exc:
            logger.error("Failed to initialize BlinkTracker shape_predictor: %s", exc)
            self.predictor = None
            self.detector = None
            self.available = False

    def is_available(self) -> bool:
        return self.available and self.predictor is not None

    def _get_state(self, device_id: str) -> DeviceBlinkState:
        if device_id not in self._states:
            self._states[device_id] = DeviceBlinkState()
        return self._states[device_id]

    def reset(self, device_id: str | None = None) -> None:
        if device_id is None:
            self._states.clear()
        else:
            self._states.pop(device_id, None)

    def consume_blink(self, device_id: str) -> None:
        state = self._states.get(device_id)
        if state is not None:
            state.last_blink_at = None
            state.last_blink_center = None

    def has_recent_blink(
        self,
        device_id: str,
        within: float = 5.0,
        near_center: tuple[float, float] | None = None,
        frame_width: int = 400,
        now: float | None = None,
    ) -> bool:
        state = self._states.get(device_id)
        if state is None or state.last_blink_at is None or state.last_blink_center is None:
            return False

        current_time = time.monotonic() if now is None else now
        if current_time - state.last_blink_at > within:
            return False

        if near_center is not None and frame_width > 0:
            cx, cy = near_center
            bx, by = state.last_blink_center
            dist = math.hypot(cx - bx, cy - by)
            if dist > 0.25 * frame_width:
                return False

        return True

    def handle_no_face(self, device_id: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        state = self._states.get(device_id)
        if state is not None:
            if state.last_seen > 0.0 and (now - state.last_seen > 1.0):
                state.samples.clear()
                state.last_center = None

    def update(
        self,
        device_id: str,
        ear_val: float,
        center: tuple[float, float],
        frame_width: int,
        now: float | None = None,
    ) -> bool:
        """Update tracker with an EAR observation and return True if a blink occurred."""
        now = time.monotonic() if now is None else now
        state = self._get_state(device_id)

        # 1. Reset if face was lost for > 1s
        if state.last_seen > 0.0 and (now - state.last_seen > 1.0):
            state.samples.clear()
            state.last_center = None

        # 2. Reset if face center jumped > 25% of frame width
        if state.last_center is not None and frame_width > 0:
            jump = math.hypot(center[0] - state.last_center[0], center[1] - state.last_center[1])
            if jump > 0.25 * frame_width:
                state.samples.clear()
                state.last_blink_at = None
                state.last_blink_center = None

        state.last_seen = now
        state.last_center = center
        state.samples.append((now, ear_val, center))

        # Evict samples older than 3.0 seconds
        cutoff = now - 3.0
        while state.samples and state.samples[0][0] < cutoff:
            state.samples.popleft()

        if len(state.samples) < 3:
            return False

        # Compute adaptive baseline (median of EAR samples in 3s window)
        ears = [s[1] for s in state.samples]
        baseline = float(np.median(ears))
        if baseline < 0.05:
            return False

        ratio = (
            self.closed_ratio
            if self.closed_ratio is not None
            else getattr(settings, "liveness_closed_ratio", 0.75)
        )
        closed_threshold = ratio * baseline

        # Check blink pattern: OPEN -> CLOSED (>=1 sample) -> OPEN RECENT
        last_t, last_ear, last_center = state.samples[-1]
        if last_ear < closed_threshold:
            return False

        prev_t, prev_ear, _ = state.samples[-2]
        if prev_ear >= closed_threshold:
            return False

        # Find continuous closed streak ending at index -2
        idx = len(state.samples) - 2
        close_end_t = state.samples[idx][0]
        while idx >= 0 and state.samples[idx][1] < closed_threshold:
            idx -= 1

        if idx < 0:
            return False

        close_start_t = state.samples[idx + 1][0]
        closed_duration = close_end_t - close_start_t
        blink_duration = last_t - close_start_t

        if blink_duration <= 0.8 and closed_duration <= 0.8:
            state.last_blink_at = last_t
            state.last_blink_center = last_center
            return True

        return False

    def process_frame(
        self,
        device_id: str,
        frame: np.ndarray,
        now: float | None = None,
    ) -> bool:
        if not self.is_available() or frame is None or not isinstance(frame, np.ndarray) or frame.ndim != 3:
            return False

        now = time.monotonic() if now is None else now
        height, width = frame.shape[:2]

        det, reason = self.detector.detect_largest(frame)
        if det is None or reason != "ok":
            self.handle_no_face(device_id, now)
            return False

        import dlib

        x, y, w, h = det.box
        rect = dlib.rectangle(int(x), int(y), int(x + w), int(y + h))
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        try:
            shape = self.predictor(gray, rect)
            left_eye = [(shape.part(i).x, shape.part(i).y) for i in range(36, 42)]
            right_eye = [(shape.part(i).x, shape.part(i).y) for i in range(42, 48)]
            ear_avg = (ear(left_eye) + ear(right_eye)) / 2.0
            return self.update(device_id, ear_avg, det.center, width, now)
        except Exception:
            logger.exception("Shape prediction failed on device %s", device_id)
            return False


tracker = BlinkTracker()
