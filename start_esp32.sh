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

# Tự động gửi lệnh tối ưu siêu mượt (QVGA 320x240 + Quality 16) qua API /control
CAM_IP=$(echo "$CAMERA_CAPTURE_URL" | sed -E 's|https?://([^:/]+).*|\1|')
if [ -n "$CAM_IP" ]; then
    echo "-> Đang áp cấu hình siêu mượt (QVGA 320x240, Quality 16) tới camera..."
    curl -s -m 2 "http://${CAM_IP}/control?var=framesize&val=QVGA" >/dev/null 2>&1 || true
    curl -s -m 2 "http://${CAM_IP}/control?var=quality&val=16" >/dev/null 2>&1 || true
fi

cd "$SCRIPT_DIR/backend"

echo "Đang kết nối Camera ESP32-CAM đến backend..."
python3 camera_bridge.py
