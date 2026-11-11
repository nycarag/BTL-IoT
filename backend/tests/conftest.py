"""Cô lập CSDL cho toàn bộ bộ test.

Vài test chạy lifespan thật của app (TestClient dạng context manager). Lifespan gọi init_db()
và bật bộ hẹn giờ ca tự động, cả hai dùng engine mặc định của app.database. Nếu không đổi
DATABASE_URL trước khi app được import, mỗi lần chạy test bộ hẹn giờ sẽ đóng/mở ca và ghi vắng
ngay trong data/attendance.db thật.
"""

import atexit
import os
import tempfile

import dotenv

# Test không được phụ thuộc .env của máy chạy. File .env tinh chỉnh cho buổi demo (STABLE_FRAMES=1,
# LIVENESS_MODE=passive, ngưỡng nhận diện nới) làm sai các test về cổng ổn định và chớp mắt.
dotenv.load_dotenv = lambda *args, **kwargs: False

_tmp = tempfile.TemporaryDirectory(prefix="btl_iot_test_")
atexit.register(_tmp.cleanup)
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}/default.db"

# Tiến trình con trích vector khuôn mặt mất vài giây để khởi động; chỉ test riêng của nó mới bật.
os.environ["RECOGNITION_PROCESS"] = "0"
