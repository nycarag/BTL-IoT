#!/bin/bash
# ==============================================================================
# HỆ THỐNG ĐIỂM DANH SINH VIÊN AIoT (FASTAPI + REACT + MINIFASNETV2)
# Nhóm 05 - Lớp D23CTAT01-B - Học viện Công nghệ Bưu chính Viễn thông (PTIT)
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASHASH_SOURCE[0]:-$0}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================================================="
echo ">>> KHỞI ĐỘNG HỆ THỐNG ĐIỂM DANH SINH VIÊN AIoT - NHÓM 05 (PTIT) <<<"
echo "=========================================================================="

# 1. Nạp cơ sở dữ liệu nếu chưa có
if [ ! -f "data/attendance.db" ]; then
    echo "[1/3] Khởi tạo cơ sở dữ liệu và tự động nạp vector khuôn mặt sinh viên..."
    python3 backend/seed.py
else
    echo "[1/3] Cơ sở dữ liệu SQLite đã sẵn sàng."
fi

# 2. Khởi chạy FastAPI Server (kèm React Frontend Kiosk tích hợp sẵn)
echo "[2/3] Đang khởi chạy FastAPI Server tại cổng 8000..."
echo "  -> Dashboard & Kiosk Web UI: http://localhost:8000"
echo "  -> Swagger API Docs:        http://localhost:8000/docs"
echo "  -> Tài khoản quản trị:       admin / admin123456"
echo "=========================================================================="
echo "LƯU Ý KẾT NỐI CAMERA:"
echo "  - Để dùng Camera ESP32-CAM: Mở thêm 1 terminal chạy: ./start_esp32.sh"
echo "  - Để dùng Webcam Laptop:    Mở thêm 1 terminal chạy: ./start_webcam.sh"
echo "=========================================================================="

cd backend
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
