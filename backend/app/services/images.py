"""Validate dimensions before OpenCV/dlib decode; reject decompression bombs."""
from __future__ import annotations

import cv2
import numpy as np

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 4_000_000
MIN_IMAGE_DIMENSION = 64


def decode_image(body: bytes) -> np.ndarray:
    """Decode JPEG/PNG bytes to BGR ndarray and validate dimensions once."""
    if not body or len(body) > MAX_IMAGE_BYTES:
        raise ValueError("Image is empty or larger than 5 MiB")
    frame = cv2.imdecode(np.frombuffer(body, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("Invalid or oversized image")
    validate_frame(frame)
    return frame


def validate_frame(frame: np.ndarray) -> None:
    """Validate minimum and maximum image dimensions on BGR ndarray."""
    if not isinstance(frame, np.ndarray) or frame.ndim != 3:
        raise ValueError("Invalid image")
    height, width = frame.shape[:2]
    if min(width, height) < MIN_IMAGE_DIMENSION or width * height > MAX_IMAGE_PIXELS:
        raise ValueError("Image dimensions must be at least 64×64 and at most 4 megapixels")


def validate_image(body: bytes) -> np.ndarray:
    """Legacy helper for bytes validation; decodes and validates dimensions."""
    return decode_image(body)
