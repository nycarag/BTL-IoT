#!/bin/bash
# ==============================================================================
# KẾT NỐI CAMERA ESP32-CAM (WI-FI HOTSPOT / SOFTAP) ĐẾN BACKEND
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

# Đọc CAMERA_CAPTURE_URL từ .env ở gốc repo nếu biến môi trường chưa đặt
if [ -z "${CAMERA_CAPTURE_URL:-}" ] && [ -f "$SCRIPT_DIR/.env" ]; then
    ENV_URL=$(grep -E '^\s*CAMERA_CAPTURE_URL=' "$SCRIPT_DIR/.env" | cut -d'=' -f2- | tr -d ' "' || true)
    if [ -n "$ENV_URL" ]; then
        CAMERA_CAPTURE_URL="$ENV_URL"
    fi
fi

# Nếu CAMERA_CAPTURE_URL vẫn chưa đặt: gọi tools/find_esp32.sh để tự động phát hiện
if [ -z "${CAMERA_CAPTURE_URL:-}" ]; then
    echo "Đang tự động dò tìm camera ESP32-CAM trên mạng qua tools/find_esp32.sh..."
    if FOUND_URL=$("$SCRIPT_DIR/tools/find_esp32.sh" 2>/dev/null); then
        export CAMERA_CAPTURE_URL="$FOUND_URL"
        IP=$(echo "$FOUND_URL" | sed -E 's|https?://([^:/]+).*|\1|')
        export CAMERA_STREAM_URL="http://${IP}:81/stream"
        echo "Tự động phát hiện camera ESP32-CAM: $CAMERA_CAPTURE_URL"
    else
        echo "Không tìm thấy camera trên mạng, sử dụng địa chỉ mặc định SoftAP: 192.168.4.1"
        export CAMERA_CAPTURE_URL="http://192.168.4.1/capture"
        export CAMERA_STREAM_URL="http://192.168.4.1:81/stream"
    fi
else
    # Nếu đã có CAMERA_CAPTURE_URL nhưng chưa có CAMERA_STREAM_URL thì sinh URL stream
    if [ -z "${CAMERA_STREAM_URL:-}" ]; then
        IP=$(echo "$CAMERA_CAPTURE_URL" | sed -E 's|https?://([^:/]+).*|\1|')
        export CAMERA_STREAM_URL="http://${IP}:81/stream"
    fi
fi

echo "URL Camera đang sử dụng:"
echo "  - Chụp ảnh (Capture): $CAMERA_CAPTURE_URL"
echo "  - Luồng video (Stream): $CAMERA_STREAM_URL"

# Tinh chỉnh thêm cho cảm biến (không cần nạp lại firmware), đọc từ .env nếu chưa đặt.
# Ví dụ: CAMERA_CONTROL_EXTRA="aec2=0 gainceiling=4"
if [ -z "${CAMERA_CONTROL_EXTRA:-}" ] && [ -f "$SCRIPT_DIR/.env" ]; then
    CAMERA_CONTROL_EXTRA=$(grep -E '^\s*CAMERA_CONTROL_EXTRA=' "$SCRIPT_DIR/.env" | tail -n1 | cut -d'=' -f2- | tr -d '"'"'" || true)
fi

CAM_IP=$(echo "$CAMERA_CAPTURE_URL" | sed -E 's|https?://([^:/]+).*|\1|')
if [ -n "$CAM_IP" ]; then
    # IP do hotspot cấp có thể đổi giữa các lần bật. Kiểm tra trước, để lỗi hiện ra rõ ràng
    # thay vì cầu nối lặp mãi dòng "Camera read failed".
    if curl -s -m 3 "http://${CAM_IP}/status" 2>/dev/null | grep -q '"wifi_mode"'; then
        echo "-> Camera trả lời ở ${CAM_IP}. Đang áp cấu hình siêu mượt (QVGA 320x240, Quality 16)..."
        curl -s -m 2 "http://${CAM_IP}/control?var=framesize&val=QVGA" >/dev/null 2>&1 || true
        curl -s -m 2 "http://${CAM_IP}/control?var=quality&val=16" >/dev/null 2>&1 || true
        for pair in ${CAMERA_CONTROL_EXTRA:-}; do
            if curl -sf -m 2 "http://${CAM_IP}/control?var=${pair%%=*}&val=${pair#*=}" >/dev/null 2>&1; then
                echo "   + đã áp ${pair}"
            else
                echo "   ! camera từ chối ${pair}"
            fi
        done
    else
        echo "=========================================================================="
        echo "CẢNH BÁO: camera không trả lời ở ${CAM_IP}."
        echo "  1. Kiểm tra camera đã có điện và điện thoại đang bật hotspot."
        echo "  2. IP có thể đã đổi: trên Windows chạy  ping esp32cam.local  để lấy IP mới,"
        echo "     rồi sửa hai dòng CAMERA_CAPTURE_URL và CAMERA_STREAM_URL trong file .env."
        echo "Cầu nối vẫn chạy và sẽ tự nối lại khi camera lên."
        echo "=========================================================================="
    fi
fi

cd "$SCRIPT_DIR/backend"

echo "Đang kết nối Camera ESP32-CAM đến backend..."
python3 camera_bridge.py
