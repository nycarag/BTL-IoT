# Firmware ESP32-CAM (AI Thinker) — SoftAP & Stream Tối Ưu Độ Trễ

Firmware hỗ trợ phát Wi-Fi Access Point (`192.168.4.1`) và phục vụ luồng video MJPEG độ trễ cực thấp cùng endpoint chụp ảnh snapshot độc lập.

## Kiến Trúc Cổng Dịch Vụ HTTP (Tách Port Chuẩn CameraWebServer)

Nhằm tránh hiện tượng luồng video `/stream` chiếm giữ kết nối đơn luồng của HTTP server làm treo hoặc nghẽn yêu cầu chụp ảnh snapshot, firmware khởi chạy 2 HTTP daemon độc lập:

1. **Cổng 80 (`camera_httpd`):**
   * `GET http://192.168.4.1/capture`: Chụp 1 ảnh tĩnh JPEG độ nét cao (header `Cache-Control: no-store, private`).
   * `GET http://192.168.4.1/status`: Trả về JSON trạng thái cảm biến OV2640 (`framesize`, `quality`, `psram`).
   * `GET http://192.168.4.1/flash`: Nháy đèn flash trợ sáng khi nhận diện thành công (chạy ngầm qua FreeRTOS task).
2. **Cổng 81 (`stream_httpd`):**
   * `GET http://192.168.4.1:81/stream`: Luồng video MJPEG (`multipart/x-mixed-replace;boundary=frame_boundary`) liên tục cho cầu nối laptop hoặc trình duyệt.

> [!NOTE]
> **Tương thích với Cầu nối Laptop (`camera_bridge.py`):**
> * Chế độ mặc định của hệ thống là `CAMERA_TRANSPORT=mjpeg`, cầu nối đọc trực tiếp từ `CAMERA_STREAM_URL=http://192.168.4.1:81/stream` (hoàn toàn trùng khớp cổng 81).
> * Nếu sử dụng chế độ chụp ảnh tĩnh (`CAMERA_TRANSPORT=capture`), cầu nối sẽ gọi `/capture` trên cổng 80 (`CAMERA_CAPTURE_URL=http://192.168.4.1:80/capture` hoặc `http://192.168.4.1/capture`).

## Cấu Hình Camera & Bộ Đệm Khung Hình (Nguồn Chuẩn Espressif)

* **Chế độ lấy khung hình (`grab_mode`):** `CAMERA_GRAB_LATEST` (nguồn: `esp_camera.h` - Espressif). Driver camera luôn ghi đè khung hình cũ và trả về khung hình mới nhất tại thời điểm gọi `esp_camera_fb_get()`, không xếp hàng khung cũ.
* **Bộ đệm kép (`fb_count = 2`) & Vị trí PSRAM (`CAMERA_FB_IN_PSRAM`):** Khi board nhận PSRAM (`psramFound()`), kích hoạt double-buffering trong PSRAM ngoài giúp DMA camera truyền nhận song song với luồng mạng Wi-Fi.
* **Fallback an toàn khi thiếu PSRAM:** Tự động hạ độ phân giải xuống `FRAMESIZE_QVGA` (320×240), `config.fb_count = 1` và lưu trên DRAM nội bộ (`CAMERA_FB_IN_DRAM`) để tránh tràn bộ nhớ heap.
* **Tần số xung nhịp (`xclk_freq_hz`):** Giữ nguyên `20000000` (20 MHz) theo chuẩn cảm biến OV2640 trên board AI Thinker để đảm bảo xung nhịp quét pixel ổn định, không sọc nhiễu.
* **Chất lượng nén JPEG (`jpeg_quality`):** Giữ mức `12` (dải tối ưu 10–12 theo `CameraWebServer` của Espressif).

## Quản Lý Nguồn Điện & Bảo Vệ Brownout

* **Mặc định:** Hệ thống **KHÔNG tắt** Brownout Detector (`RTC_CNTL_BROWN_OUT_REG`). Bộ giám sát điện áp thấp bảo vệ chip ESP32 khỏi lỗi hư hỏng bộ nhớ flash khi nguồn cấp không đủ tải.
* **Cờ cấu hình tùy chọn:** Nếu sử dụng nguồn điện thử nghiệm yếu gây sụt áp tức thời lúc bật Wi-Fi, có thể định nghĩa cờ `#define DISABLE_BROWNOUT` trước khi biên dịch.
* **Khuyến nghị phần cứng:** Cấp nguồn 5V/2A ổn định qua chân 5V và hàn thêm tụ hóa 100µF–470µF giữa chân 5V và GND để chống sụt áp tức thời.

## Cài Đặt & Nạp Firmware

1. Mở Arduino IDE 2.x hoặc dùng `arduino-cli`.
2. Cài đặt board package **esp32 by Espressif Systems** (phiên bản 3.x).
3. Chọn board: **AI Thinker ESP32-CAM**. Bật PSRAM trong menu công cụ.
4. Nối GPIO 0 vào GND khi nạp firmware; ngắt GPIO 0 khỏi GND và nhấn nút RESET để chạy.
5. Kiểm tra qua Serial Monitor (baud rate 9600):
   * Wi-Fi AP: `ESP32_DIEM_DANH` (mật khẩu: `12345678`)
   * IP: `192.168.4.1`
   * Snapshot: `http://192.168.4.1/capture`
   * Stream: `http://192.168.4.1:81/stream`
