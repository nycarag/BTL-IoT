# Hệ Thống Điểm Danh Sinh Viên AIoT

Hệ thống điểm danh sinh viên tự động thu nhận hình ảnh từ ESP32-CAM (hoặc webcam), xử lý qua máy chủ FastAPI và hiển thị kết quả thời gian thực trên giao diện React kiosk. Quá trình nhận diện kết hợp phát hiện khuôn mặt, kiểm tra chớp mắt, chống giả mạo và đối soát danh tính theo danh sách lớp.

## Thông tin nhóm

| Mục | Nội dung |
|---|---|
| Học phần | IOT và ứng dụng (INT14149) |
| Nhóm lớp tín chỉ | INT14149-20261-CT02 |
| Nhóm | Nhóm 05 — Lớp D23CTAT01-B |
| Cơ sở | Học viện Công nghệ Bưu chính Viễn thông (PTIT) |
| Giảng viên hướng dẫn | TS. Lê Văn Vịnh |
| Thành viên thực hiện | Đỗ Trung Kiên (B23DCAT156), Nguyễn Đăng Khoa (B23DCAT153), Hoàng Hoàng Tuấn (B23DCAT320) |

## Kiến trúc hệ thống

```text
ESP32-CAM / Webcam ──(HTTP MJPEG/JPEG)──> Camera Bridge ──(HTTP/WS)──> FastAPI Backend
                                                                           │
               ┌───────────────────────────────────────────────────────────┤
               ▼                                                           ▼
Pipeline AI (YuNet, MiniFASNet, dlib)                     SQLite / Web Audio / React Kiosk
```

Chi tiết các luồng xử lý và giao thức truyền tải xem tại [docs/architecture.md](docs/architecture.md).

## Pipeline nhận diện

- Phát hiện khuôn mặt: YuNet (ngưỡng điểm 0.8, diện tích tối thiểu 0.03, độ nét Laplacian 20, ROI mặc định 0.22–0.78 ngang và 0.15–0.85 dọc), tự động chuyển sang Haar cascade khi thiếu file mô hình hoặc nạp lỗi.
- Chống giả mạo (PAD): MiniFASNetV2 ONNX tensor `(1, 3, 80, 80)`, mở rộng vùng cắt tỉ lệ 2.7 kèm dịch chuyển hộp vào trong biên ảnh, ngưỡng phân loại khuôn mặt thật 0.45.
- Kiểm tra chớp mắt (Active Liveness): Thuật toán EAR với dlib 68 mốc điểm chạy trên luồng preview (tối đa 10.0 Hz), ngưỡng nhắm mắt thích ứng bằng 0.75 trung vị 3 giây gần nhất, hiệu lực trong 5.0 giây và xóa dấu vết ngay sau khi ghi nhận.
- Nhận diện khuôn mặt: Mô hình dlib trích xuất vector 128 chiều thô (không chuẩn hóa L2), hỗ trợ 1–5 ảnh mẫu mỗi sinh viên, so khớp khoảng cách Euclid với ngưỡng chấp nhận 0.52 và khoảng cách an toàn giữa hai ứng viên tối thiểu 0.05.

## Cài đặt và khởi chạy

1. Cài đặt môi trường Python (lưu ý: `requirements.txt` ở thư mục gốc là của bản Streamlit cũ):
   ```bash
   pip install -r backend/requirements.txt -r backend/requirements-recognition.txt
   ```
2. Cấu hình biến môi trường:
   ```bash
   cp backend/.env.example .env
   ```
   Thiết lập các biến bắt buộc trong file `.env`: `ADMIN_PASSWORD`, `DEVICE_TOKEN`, và `SECRET_KEY` (chuỗi ngẫu nhiên tối thiểu 32 ký tự).
3. Khởi chạy hệ thống:
   ```bash
   ./start.sh
   ```
   Hệ thống tự nạp danh sách 36 sinh viên vào `data/attendance.db` nếu chưa có cơ sở dữ liệu.
4. Truy cập giao diện:
   - Giao diện Kiosk và quản trị: `http://localhost:8000` (tài khoản `admin`, mật khẩu trong `.env`, mặc định `admin123456`).
   - Tài liệu API Swagger: `http://localhost:8000/docs`.
5. Kết nối camera:
   - Qua Web UI: Vào tab Thiết bị & vùng điểm danh, chọn bật camera laptop hoặc ESP32-CAM.
   - Qua terminal riêng: Chạy `./start_webcam.sh` để dùng webcam laptop, hoặc kết nối Wi-Fi SoftAP `ESP32_DIEM_DANH` bằng mật khẩu đã đặt trong `firmware/esp32_cam_softap/config.h` (tạo từ `config.example.h`), rồi chạy `./start_esp32.sh`.
6. Chạy với Docker Compose:
   ```bash
   docker compose up --build -d
   ```
   Giao diện web mở tại cổng 8080 (`http://localhost:8080`), backend API tại cổng 8000 (`http://localhost:8000`). Chi tiết xem tại [docs/docker.md](docs/docker.md).

## Lưu ý nâng cấp từ bản cũ

- Đăng ký lại khuôn mặt: Bản mới so khớp đa mẫu trên vector thô 128D của dlib thay vì vector chuẩn hóa L2 cũ; dữ liệu cũ vẫn nạp được nhưng sẽ ghi log cảnh báo và giảm độ chính xác.
- Đặt `SECRET_KEY` cố định trong file `.env`: Tránh để trống khiến máy chủ tự sinh khóa ngẫu nhiên trong bộ nhớ và hủy toàn bộ token đăng nhập sau mỗi lần khởi động lại.
- Nạp lại firmware ESP32-CAM: Sử dụng mã nguồn trong `firmware/esp32_cam_softap/` phân tách cổng 80 (cấu hình, chụp ảnh `/capture`) và cổng 81 (luồng MJPEG `/stream`).
- Chế độ `LIVENESS_MODE=off`: Đặt giá trị này trong `.env` khi cần tắt kiểm tra chớp mắt trong trường hợp camera đặt xa, mạng chập chờn hoặc phục vụ thử nghiệm nhanh.

## Giới hạn đã biết

- EAR chưa ngăn được video phát lại chất lượng cao có người thật đang chớp mắt.
- Chưa đo kiểm thực địa tỷ lệ FAR và FRR trên tập dữ liệu lớn.
- Chưa đo kiểm độ ổn định sóng Wi-Fi của ESP32-CAM trong môi trường nhiều vật cản.

## Kiểm thử

Chạy kiểm thử tự động với pytest:

```bash
PYTHONPATH=backend pytest backend/tests -q
```

Kết quả đo được: 97 passed, 3 warnings (cảnh báo DeprecationWarning từ thư viện bên ngoài). Chi tiết kiểm thử xem tại [docs/test-report.md](docs/test-report.md).

## Tài liệu liên quan

- [docs/architecture.md](docs/architecture.md): Thiết kế kiến trúc phân tầng, đặc tả API và giao thức WebSocket.
- [docs/camera-softap.md](docs/camera-softap.md): Hướng dẫn cấu hình phần cứng ESP32-CAM và mạng SoftAP.
- [docs/docker.md](docs/docker.md): Hướng dẫn đóng gói và triển khai hệ thống bằng Docker Compose.
- [docs/model-evaluation.md](docs/model-evaluation.md): Quy trình hiệu chuẩn và đánh giá mô hình nhận diện, PAD.
- [docs/test-report.md](docs/test-report.md): Báo cáo kiểm thử tự động và kịch bản đầu-cuối.
- [BAO_CAO_THUYET_TRINH.md](BAO_CAO_THUYET_TRINH.md): Tóm tắt nội dung báo cáo phục vụ thuyết trình.
- [docs/BaoCao_BTL_IoT_Nhom05.pdf](docs/BaoCao_BTL_IoT_Nhom05.pdf): Báo cáo tổng kết bài tập lớn của nhóm.
