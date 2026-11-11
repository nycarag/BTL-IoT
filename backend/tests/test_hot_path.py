"""Những thứ chạy ở mỗi khung AI không được làm đứng vòng lặp sự kiện đang chuyển khung hình xem trước."""

import asyncio
import dataclasses
import unittest
from unittest.mock import patch

import numpy as np

from app.core.config import settings
from app.database import engine
from app.services import face_recognition
from app.services.face_recognition import FaceRecognitionAdapter, encode_off_loop, shutdown_encoder


class TestDatabaseWrites(unittest.TestCase):
    def test_app_engine_commits_without_fsync_per_write(self):
        with engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql("PRAGMA journal_mode").scalar(), "wal")
            self.assertEqual(connection.exec_driver_sql("PRAGMA synchronous").scalar(), 1)  # 1 = NORMAL


class TestEncodeOffLoop(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(7)
        self.frame = rng.integers(0, 255, size=(240, 320, 3), dtype=np.uint8)
        self.box = (100, 60, 120, 120)
        enabled = dataclasses.replace(settings, recognition_process=True)
        patcher = patch.object(face_recognition, "settings", enabled)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(setattr, face_recognition, "_pool_broken", False)
        self.addCleanup(shutdown_encoder)

    def _real_adapter(self) -> FaceRecognitionAdapter:
        adapter = FaceRecognitionAdapter()
        if adapter.engine is None:
            self.skipTest("Chưa cài requirements-recognition.txt (dlib)")
        return adapter

    def test_stand_in_adapter_is_called_directly_without_starting_a_worker(self):
        class StandIn:
            def encode(self, frame, box):
                return "vector"

        self.assertEqual(asyncio.run(encode_off_loop(StandIn(), self.frame, self.box)), "vector")
        self.assertIsNone(face_recognition._pool)

    def test_worker_process_returns_the_same_vector_as_in_process_encoding(self):
        adapter = self._real_adapter()

        from_worker = asyncio.run(encode_off_loop(adapter, self.frame, self.box))

        self.assertIsNotNone(face_recognition._pool)
        np.testing.assert_allclose(from_worker, adapter.encode(self.frame, self.box))

    def test_broken_worker_falls_back_to_in_process_encoding(self):
        adapter = self._real_adapter()

        class BrokenPool:
            def submit(self, *args, **kwargs):
                raise RuntimeError("worker died")

            def shutdown(self, *args, **kwargs):
                pass

        with patch.object(face_recognition, "_pool", BrokenPool()), self.assertLogs(face_recognition.logger, "ERROR"):
            vector = asyncio.run(encode_off_loop(adapter, self.frame, self.box))

        self.assertEqual(vector.shape, (128,))
        self.assertTrue(face_recognition._pool_broken)


if __name__ == "__main__":
    unittest.main()
