#!/bin/bash
# ==============================================================================
# KẾT NỐI CAMERA ĐIỆN THOẠI (CAMERA IP QUA WI-FI) ĐẾN BACKEND
# ==============================================================================

set -e

if [ -z "${1:-}" ] || [[ "$1" != http://* ]]; then
    echo "Cách dùng: $0 http://<IP điện thoại>:8080 [snapshot]"
    echo "Ví dụ:    $0 http://192.168.1.15:8080"
    echo "          $0 http://192.168.1.15:8080 snapshot"
    exit 1
fi

BASE_URL="${1%/}"

export CAMERA_DEVICE_ID="${CAMERA_DEVICE_ID:-phone-cam-02}"
export CAMERA_DEVICE_NAME="${CAMERA_DEVICE_NAME:-Điện thoại · camera IP}"
export CAMERA_CAPTURE_URL="${BASE_URL}${PHONE_CAPTURE_PATH:-/shot.jpg}"
export CAMERA_STREAM_URL="${BASE_URL}${PHONE_STREAM_PATH:-/video}"
export CAMERA_INTERVAL_SECONDS="${CAMERA_INTERVAL_SECONDS:-1}"

if [ "${2:-}" = "snapshot" ]; then
    export CAMERA_TRANSPORT=snapshot
    export CAMERA_PREVIEW_FPS=5
fi

# Kiểm tra trước: camera phải trả về HTTP 200 tại URL chụp ảnh
HTTP_CODE=$(curl -s -m 4 -o /dev/null -w "%{http_code}" "$CAMERA_CAPTURE_URL" || true)
if [ "$HTTP_CODE" != "200" ]; then
    echo "LỖI: Camera không phản hồi tại $CAMERA_CAPTURE_URL (HTTP status: ${HTTP_CODE:-không có phản hồi})."
    echo "  1. Điện thoại và laptop đã kết nối cùng mạng Wi-Fi chưa?"
    echo "  2. Ứng dụng camera IP trên điện thoại đã bấm Start server chưa?"
    echo "  3. Thử mở URL trên trình duyệt laptop: $CAMERA_CAPTURE_URL"
    exit 1
fi

echo "Khởi chạy camera phụ (Điện thoại IP Camera):"
echo "  - Tên thiết bị:        $CAMERA_DEVICE_NAME ($CAMERA_DEVICE_ID)"
echo "  - Chụp ảnh (Capture):  $CAMERA_CAPTURE_URL"
echo "  - Luồng video (Stream): $CAMERA_STREAM_URL"
echo "  - Chu kỳ gửi AI:       ${CAMERA_INTERVAL_SECONDS}s"
if [ "${CAMERA_TRANSPORT:-}" = "snapshot" ]; then
    echo "  - Chế độ truyền tải:   snapshot (FPS: ${CAMERA_PREVIEW_FPS})"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

cd backend && exec python3 camera_bridge.py
