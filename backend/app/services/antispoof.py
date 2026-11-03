"""MiniFASNetV2 ONNX adapter following minivision Silent-Face-Anti-Spoofing and yakhyo.

BGR float32 0..255, expanded crop 2.7 with box shifting near boundaries,
real class index 1. Thresholds require local camera calibration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.core.config import ROOT_DIR, settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PadResult:
    is_real: bool
    reason: str
    score: float | None = None


def _get_new_box(
    src_w: int,
    src_h: int,
    bbox: tuple[int, int, int, int],
    scale: float,
) -> tuple[int, int, int, int]:
    """Calculate expanded face bounding box following Minivision Silent-Face-Anti-Spoofing.

    Shifts the box into the frame boundaries when near edges instead of truncating,
    preserving the expanded aspect ratio and context.
    """
    x, y, box_w, box_h = bbox
    scale = min((src_h - 1) / box_h, min((src_w - 1) / box_w, scale))

    new_width = box_w * scale
    new_height = box_h * scale
    center_x = x + box_w / 2.0
    center_y = y + box_h / 2.0

    left_top_x = center_x - new_width / 2.0
    left_top_y = center_y - new_height / 2.0
    right_bottom_x = center_x + new_width / 2.0
    right_bottom_y = center_y + new_height / 2.0

    if left_top_x < 0:
        right_bottom_x -= left_top_x
        left_top_x = 0.0

    if left_top_y < 0:
        right_bottom_y -= left_top_y
        left_top_y = 0.0

    if right_bottom_x > src_w - 1:
        left_top_x -= right_bottom_x - src_w + 1
        right_bottom_x = float(src_w - 1)

    if right_bottom_y > src_h - 1:
        left_top_y -= right_bottom_y - src_h + 1
        right_bottom_y = float(src_h - 1)

    return (
        max(0, int(left_top_x)),
        max(0, int(left_top_y)),
        min(src_w - 1, int(right_bottom_x)),
        min(src_h - 1, int(right_bottom_y)),
    )


def prepare_face(
    frame: np.ndarray,
    box: tuple[int, int, int, int],
    size: tuple[int, int] = (80, 80),
    scale: float = 2.7,
) -> np.ndarray:
    if frame is None or not isinstance(frame, np.ndarray) or frame.ndim != 3:
        raise ValueError("invalid image")

    height, width = frame.shape[:2]
    x, y, w, h = box
    if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > width or y + h > height:
        raise ValueError("invalid face box")

    left, top, right, bottom = _get_new_box(width, height, box, scale)
    crop = frame[top : bottom + 1, left : right + 1]
    if crop.size == 0:
        raise ValueError("empty face crop")
    resized = cv2.resize(crop, size[::-1])
    return np.ascontiguousarray(resized.transpose(2, 0, 1)[None], dtype=np.float32)


class AntiSpoofAdapter:
    def __init__(self) -> None:
        self.session = None
        self.reason = "PAD model is not configured"
        self.model = "MiniFASNetV2 ONNX"

        path = Path(settings.pad_model_path) if settings.pad_model_path else None
        if path is None:
            return
        if not path.is_absolute():
            path = ROOT_DIR / path
        if not path.is_file():
            self.reason = "PAD model file is missing"
            return
        try:
            import onnxruntime as ort

            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            session = ort.InferenceSession(
                str(path), sess_options=options, providers=["CPUExecutionProvider"]
            )
            input_info = session.get_inputs()[0]
            if input_info.type != "tensor(float)" or input_info.shape[1:] != [3, 80, 80]:
                raise ValueError("Expected MiniFASNet input N×3×80×80 float32")
            self.input_name = input_info.name
            self.output_name = session.get_outputs()[0].name
            self.session = session
            self.reason = (
                "ready"
                if settings.pad_calibrated
                else "PAD threshold needs calibration on this camera"
            )
        except Exception:
            logger.exception("PAD model load failed")
            self.reason = "PAD model or ONNX runtime incompatible; see server log"

    @property
    def ready(self) -> bool:
        return (
            self.session is not None
            and settings.pad_calibrated
            and 0.0 < settings.pad_real_threshold < 1.0
        )

    def evaluate(
        self,
        frame: np.ndarray,
        box: tuple[int, int, int, int] | None = None,
    ) -> PadResult:
        if frame is None or not isinstance(frame, np.ndarray) or frame.ndim != 3 or box is None:
            return PadResult(False, "valid detected face is required")
        if self.session is None:
            return PadResult(False, self.reason)
        try:
            tensor = prepare_face(frame, box, scale=settings.pad_crop_scale)
            logits = np.asarray(self.session.run([self.output_name], {self.input_name: tensor})[0])
            if logits.shape != (1, 3) or not np.isfinite(logits).all():
                return PadResult(False, "invalid PAD output")
            probs = np.exp(logits - logits.max(axis=1, keepdims=True))
            probs /= probs.sum(axis=1, keepdims=True)
            score = float(probs[0, 1])

            if not self.ready:
                return PadResult(False, self.reason, score)

            passed = int(np.argmax(probs[0])) == 1 and score >= settings.pad_real_threshold

            return PadResult(
                passed,
                "PAD passed" if passed else "spoof or uncertain PAD score",
                score,
            )
        except Exception:
            logger.exception("PAD inference failed")
            return PadResult(False, "PAD inference error")
