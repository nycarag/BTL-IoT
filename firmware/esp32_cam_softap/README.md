# Firmware ESP32-CAM SoftAP — Chuẩn Hóa Cổng & Giảm Độ Trễ

Sketch `esp32_cam_softap.ino` cung cấp giải pháp máy ảnh tự phát Wi-Fi Access Point (`192.168.4.1`) để laptop kết nối và thu nhận khung hình qua cầu nối [`backend/camera_bridge.py`](../../backend/camera_bridge.py).

## Kiến Trúc Cổng Dịch Vụ HTTP (Chuẩn CameraWebServer)

Nhằm tách biệt hoàn toàn luồng truyền video streaming liên tục khỏi các truy vấn lấy ảnh snapshot hoặc kiểm tra trạng thái, hệ thống sử dụng 2 HTTP server riêng biệt:

1. **Cổng 80 (`captureServer`):**
   * Snapshot ảnh tĩnh: `http://192.168.4.1/capture` (hoặc `http://192.168.4.1:80/capture`).
   * Trạng thái cảm biến: `http://192.168.4.1/status`.
2. **Cổng 81 (`streamServer`):**
   * Luồng video MJPEG: `http://192.168.4.1:81/stream` (luồng khung hình liên tục cho cầu nối).

## Cải Tiến Kỹ Thuật (Nguồn Chuẩn Espressif)

1. **Giảm độ trễ khung hình (`CAMERA_GRAB_LATEST`):**
   * Đặt `config.grab_mode = CAMERA_GRAB_LATEST` (nguồn: `esp_camera.h` - Espressif). Driver luôn ghi đè khung hình cũ trong hàng đợi và chỉ trả về khung hình mới nhất khi gọi `esp_camera_fb_get()`.
2. **Tối ưu hóa bộ đệm khung hình (PSRAM / DRAM):**
   * Khi board có PSRAM (`psramFound()`): kích hoạt `config.fb_count = 2` và `config.fb_location = CAMERA_FB_IN_PSRAM` ở độ phân giải `FRAMESIZE_CIF` (400×296).
   * Khi board không có PSRAM: tự động chuyển sang `config.fb_count = 1`, `config.fb_location = CAMERA_FB_IN_DRAM` và hạ độ phân giải về `FRAMESIZE_QVGA` (320×240) để đảm bảo không bị tràn DRAM nội bộ.
3. **Loại bỏ độ trễ nhân tạo trong vòng lặp stream:**
   * Đã gỡ bỏ hoàn toàn lệnh `delay(80)` trong hàm `streamHandler`. Driver camera và phần cứng DMA tự điều tiết nhịp đọc khung hình theo chu kỳ cảm biến OV2640, cho phép luồng stream đạt 25–30 FPS thực tế.
   * Khi socket mạng đóng hoặc gửi chunk thất bại, hàm lập tức giải phóng bộ đệm `esp_camera_fb_return(frame)` và thoát `break` ngay, không rò rỉ bộ nhớ.
4. **Bảo vệ sụt áp (Brownout):**
   * Mặc định **bật** Brownout Detector để bảo vệ chip và bộ nhớ flash.
   * Chỉ vô hiệu hóa khi người dùng chủ động cấu hình `#define DISABLE_BROWNOUT` (chỉ dùng khi kiểm thử với nguồn yếu).

## Hướng Dẫn Cài Đặt & Nạp

1. Cài đặt Arduino IDE 2.x hoặc `arduino-cli` với board package **esp32 by Espressif Systems 3.x**.
2. Chọn board: **AI Thinker ESP32-CAM**.
3. Sao chép `config.example.h` thành `config.h` trong cùng thư mục; thiết lập `AP_SSID` và `AP_PASSWORD` (mật khẩu $\ge 8$ ký tự).
4. Nối GPIO 0 vào GND để nạp; tháo GPIO 0 và bấm nút Reset sau khi nạp xong. Serial baud rate: 115200.
5. Cấu hình cầu nối trên laptop theo hướng dẫn tại [docs/camera-softap.md](../../docs/camera-softap.md).
