#!/usr/bin/env bash
# ==============================================================================
# TỰ ĐỘNG DÒ TÌM ĐỊA CHỈ IP CAMERA ESP32-CAM TRÊN MẠNG
# Trả về duy nhất 1 dòng URL capture: http://<IP>/capture
# ==============================================================================
set -euo pipefail

# a) Thử mDNS qua avahi-resolve-host-name (timeout 3s)
if command -v avahi-resolve-host-name >/dev/null 2>&1; then
    ip_mdns=$(timeout 3s avahi-resolve-host-name -4 esp32cam.local 2>/dev/null | awk '{print $2}' | grep -Eo '([0-9]{1,3}\.){3}[0-9]{1,3}' || true)
    if [ -n "$ip_mdns" ]; then
        status_mdns=$(curl -s -m 2 "http://$ip_mdns/status" || true)
        if echo "$status_mdns" | grep -q '"wifi_mode"'; then
            echo "http://$ip_mdns/capture"
            exit 0
        fi
    fi
fi

# b) Thử SoftAP mặc định 192.168.4.1 (timeout 1s)
status_ap=$(curl -s -m 1 "http://192.168.4.1/status" || true)
if echo "$status_ap" | grep -q '"wifi_mode"'; then
    echo "http://192.168.4.1/capture"
    exit 0
fi

# c) Quét subnet riêng tư (/24 đến /30) của card Wi-Fi / mạng hiện tại qua nmap (port 81)
if command -v nmap >/dev/null 2>&1; then
    # Tìm card Wi-Fi (wl*) trước, nếu không có lấy interface mạng mặc định
    dev=$(ip -o link show 2>/dev/null | awk -F': ' '{print $2}' | grep -E '^wl' | head -n1 || true)
    if [ -z "$dev" ]; then
        dev=$(ip -4 route show default 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="dev") print $(i+1)}' | head -n1 || true)
    fi

    if [ -n "$dev" ]; then
        cidr=$(ip -4 -o addr show dev "$dev" 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="inet") print $(i+1)}' | head -n1 || true)
        subnet=""
        if [ -n "$cidr" ]; then
            subnet=$(python3 -c '
import sys, ipaddress
try:
    if len(sys.argv) > 1 and sys.argv[1]:
        iface = ipaddress.IPv4Interface(sys.argv[1])
        net = iface.network
        privates = [ipaddress.IPv4Network("10.0.0.0/8"), ipaddress.IPv4Network("172.16.0.0/12"), ipaddress.IPv4Network("192.168.0.0/16")]
        if 24 <= net.prefixlen <= 30 and any(net.subnet_of(p) for p in privates):
            print(net)
except Exception:
    pass
' "$cidr" 2>/dev/null || true)
        fi

        if [ -n "$subnet" ]; then
            # Quét cổng 81 của các host trong subnet
            candidates=$(nmap -n -p 81 --open -T4 --host-timeout 2s "$subnet" 2>/dev/null | awk '/Nmap scan report for/ { ip=$NF } /81\/tcp +open/ { print ip }' || true)
            for cand_ip in $candidates; do
                cand_status=$(curl -s -m 1 "http://$cand_ip/status" || true)
                if echo "$cand_status" | grep -q '"wifi_mode"'; then
                    echo "http://$cand_ip/capture"
                    exit 0
                fi
            done
        fi
    fi
fi

# Không tìm thấy camera ESP32-CAM
cat >&2 << 'EOF'
KHÔNG TÌM THẤY CAMERA ESP32-CAM TRÊN MẠNG!
Hướng dẫn khắc phục:
1. Nếu camera đang ở chế độ SoftAP (tự phát Wi-Fi): Hãy kết nối máy tính vào mạng Wi-Fi 'ESP32_DIEM_DANH' (mật khẩu: 12345678).
2. Nếu camera bắt hotspot: Đảm bảo ESP32-CAM và máy tính cùng kết nối vào một mạng Wi-Fi. Kiểm tra địa chỉ IP trên Serial Monitor của ESP32 (baud rate 9600).
3. Đảm bảo nguồn điện 5V cấp cho ESP32-CAM ổn định và đèn đỏ nhấp nháy báo sẵn sàng.
EOF
exit 1
