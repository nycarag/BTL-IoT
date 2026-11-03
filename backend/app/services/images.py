"""Validate dimensions before OpenCV/dlib decode; reject decompression bombs."""
from __future__ import annotations

import io
import warnings

import cv2
import numpy as np
from PIL import Image

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 4_000_000
MIN_IMAGE_DIMENSION = 64


def decode_image(body: bytes) -> np.ndarray:
    """Validate image header lazily with Pillow, then decode once to BGR ndarray."""
    if not body or len(body) > MAX_IMAGE_BYTES:
        raise ValueError("Image is empty or larger than 5 MiB")

    # (a) Mở header bằng PIL (lazy, không decode pixel), bắt DecompressionBombWarning/Error
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(body)) as image:
                if image.format not in {"JPEG", "PNG"}:
                    raise ValueError("Only JPEG and PNG images are accepted")
                width, height = image.size
                if min(width, height) < MIN_IMAGE_DIMENSION or width * height > MAX_IMAGE_PIXELS:
                    raise ValueError("Image dimensions must be at least 64×64 and at most 4 megapixels")
    except (OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Invalid or oversized image") from exc

    # (b) Sau đó mới giải mã pixel 1 lần duy nhất bằng cv2.imdecode
    frame = cv2.imdecode(np.frombuffer(body, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("Invalid image")
    return frame


def validate_image(body: bytes) -> np.ndarray:
    """Wrapper for backward compatibility."""
    return decode_image(body)
