#!/bin/bash
# ==============================================================================
# KẾT NỐI CAMERA WEBCAM LAPTOP ĐẾN BACKEND
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
cd "$SCRIPT_DIR/backend"

echo "Đang kết nối Webcam Laptop đến Backend..."
python3 camera_bridge.py --webcam
