#!/bin/bash
# ==============================================================================
# KHỞI CHẠY HỆ THỐNG ĐIỂM DANH AIoT 1-CLICK (NHÓM 05 - D23CTAT01-B)
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================================================="
echo ">>> KHỞI ĐỘNG HỆ THỐNG ĐIỂM DANH SINH VIÊN AIoT (NHÓM 05 - PTIT) <<<"
echo "=========================================================================="

# 1. Đảm bảo CSDL đã có
if [ ! -f "data/attendance.db" ]; then
    echo "[1/4] Khởi tạo cơ sở dữ liệu và vector khuôn mặt..."
    python3 backend/seed.py
else
    echo "[1/4] Cơ sở dữ liệu SQLite đã sẵn sàng."
fi

# 2. Khởi chạy Backend FastAPI ngầm
echo "[2/4] Đang khởi chạy Máy chủ FastAPI tại cổng 8000..."
python3 -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000 >/dev/null 2>&1 &
BACKEND_PID=$!

cleanup() {
    echo -e "\nĐang dừng hệ thống..."
    kill $BACKEND_PID 2>/dev/null || true
    exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# 3. Đợi backend sẵn sàng & mở trình duyệt
echo "[3/4] Đang mở giao diện Kiosk trên trình duyệt..."
for i in {1..20}; do
    if curl -s http://127.0.0.1:8000/health >/dev/null; then
        break
    fi
    sleep 0.3
done

# Mở trình duyệt vào Dashboard / Kiosk
xdg-open "http://localhost:8000" >/dev/null 2>&1 &

# 4. Lựa chọn nguồn Camera (Tự động chọn ESP32-CAM sau 5s nếu không bấm gì)
echo "=========================================================================="
echo "[4/4] Chọn nguồn Camera (Tự động chọn ESP32-CAM sau 5 giây):"
echo "  [1] ESP32-CAM qua Wi-Fi (Mặc định cho buổi bảo vệ)"
echo "  [2] Webcam Laptop (Dùng khi test không có bo ESP32)"
echo "=========================================================================="
choice="1"
read -t 5 -p "Nhập lựa chọn [1/2, mặc định 1]: " user_choice || true
if [ "$user_choice" = "2" ]; then
    choice="2"
fi

cd backend
if [ "$choice" = "2" ]; then
    echo -e "\n-> Đang kết nối Webcam Laptop..."
    python3 camera_bridge.py --webcam
else
    echo -e "\n-> Đang kết nối Camera ESP32-CAM (Wi-Fi SoftAP)..."
    echo "Lưu ý: Nhớ kết nối laptop vào Wi-Fi 'ESP32_DIEM_DANH' (pass: 12345678)"
    python3 camera_bridge.py
fi
