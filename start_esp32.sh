#!/bin/bash
# ==============================================================================
# KẾT NỐI CAMERA ESP32-CAM (WI-FI SOFTAP 192.168.4.1) ĐẾN BACKEND
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
cd "$SCRIPT_DIR/backend"

echo "Đang kết nối Camera ESP32-CAM qua luồng Wi-Fi SoftAP..."
python3 camera_bridge.py
