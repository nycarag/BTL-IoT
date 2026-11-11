"""Optional dlib embeddings; stored references come only from consented enrollment."""
from __future__ import annotations

import asyncio
import json
import logging
import multiprocessing
import os
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

import cv2
import numpy as np
from starlette.concurrency import run_in_threadpool

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

    def encode(self, frame: np.ndarray, box=None):
        if self.engine is None:
            raise ValueError(self.reason)
        if frame is None or not isinstance(frame, np.ndarray) or frame.ndim != 3:
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


# --- Trích vector trong tiến trình con ---------------------------------------------------------------
# dlib giữ GIL suốt một lần trích vector (đo trên máy demo, khung 320x240: khoảng 70 ms). Chạy trong
# luồng của server thì vòng lặp sự kiện đứng đúng ngần ấy thời gian: không khung xem trước nào tới được
# trình duyệt, và việc này lặp lại ở mỗi khung AI có mặt người. Tiến trình con có GIL riêng.

_pool: ProcessPoolExecutor | None = None
_pool_lock = threading.Lock()
_pool_broken = False
_worker_adapter: FaceRecognitionAdapter | None = None  # chỉ được gán trong tiến trình con


def _worker_init() -> None:
    global _worker_adapter
    parent = os.getppid()

    def exit_when_orphaned() -> None:
        # Server bị kill -9 thì tiến trình con không nhận được tín hiệu nào; tự thoát để không treo lại.
        while os.getppid() == parent:
            time.sleep(2)
        os._exit(0)

    threading.Thread(target=exit_when_orphaned, daemon=True).start()
    _worker_adapter = FaceRecognitionAdapter()


def _worker_encode(frame: np.ndarray, box):
    return _worker_adapter.encode(frame, box)


def _uses_worker(adapter) -> bool:
    return (
        settings.recognition_process
        and not _pool_broken
        and type(adapter) is FaceRecognitionAdapter
        and adapter.engine is not None
    )


def _get_pool() -> ProcessPoolExecutor:
    global _pool
    with _pool_lock:
        if _pool is None:
            # spawn chứ không fork: server đang có nhiều luồng (threadpool, ONNX, OpenCV), fork dễ kẹt khóa.
            _pool = ProcessPoolExecutor(
                max_workers=1,
                mp_context=multiprocessing.get_context("spawn"),
                initializer=_worker_init,
            )
            _pool.submit(os.getpid)  # buộc tiến trình con khởi động và nạp dlib ngay
        return _pool


def _give_up_on_worker() -> None:
    global _pool_broken
    logger.exception("Tiến trình trích vector khuôn mặt lỗi; chuyển về chạy trong luồng của server")
    _pool_broken = True
    shutdown_encoder()


def prepare_encoder(adapter) -> None:
    """Khởi động sẵn tiến trình con, để lần nhận diện đầu tiên không phải chờ nạp dlib."""
    if _uses_worker(adapter):
        try:
            _get_pool()
        except Exception:
            _give_up_on_worker()


def shutdown_encoder() -> None:
    global _pool
    with _pool_lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)


async def encode_off_loop(adapter, frame: np.ndarray, box):
    """Trích vector khuôn mặt mà không làm đứng vòng lặp sự kiện của server."""
    if _uses_worker(adapter):
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(_get_pool(), _worker_encode, frame, tuple(box))
        except ValueError:
            raise  # lỗi do ảnh hoặc khung mặt: giữ nguyên như khi chạy trong luồng
        except Exception:
            _give_up_on_worker()
    return await run_in_threadpool(adapter.encode, frame, box)
