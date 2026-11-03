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

1. Cài đặt môi trường Python:
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

## Cấu hình vận hành

Các tham số được nạp từ file `.env`, định nghĩa tại `backend/app/core/config.py`:

| Biến | Mặc định | Vai trò |
|---|---|---|
| `SECRET_KEY` | sinh tạm khi trống | Ký token đăng nhập HMAC; cần đặt cố định để token còn hiệu lực sau khi khởi động lại. |
| `DEVICE_TOKEN` | `esp32_device_secret_token_ptit` | Xác thực camera bridge và ESP32 gửi dữ liệu về backend. Đổi khi triển khai. |
| `ADMIN_PASSWORD` | `admin123456` | Mật khẩu đăng nhập quản trị viên trên giao diện web. Đổi khi triển khai. |
| `PAD_REAL_THRESHOLD` | `0.45` | Điểm MiniFASNet tối thiểu để coi là khuôn mặt thật. |
| `RECOGNITION_THRESHOLD` | `0.52` | Ngưỡng khoảng cách Euclid để chấp nhận khớp khuôn mặt. |
| `RECOGNITION_MARGIN` | `0.05` | Chênh lệch khoảng cách tối thiểu giữa hai ứng viên gần nhất. |
| `LIVENESS_MODE` | `blink` | Kiểm tra chớp mắt (blink) hoặc tắt khi thử nghiệm (off). |
| `STABLE_FRAMES` | `3` | Số khung hình ổn định liên tiếp trước khi nhận diện. |
| `FRAME_INTERVAL_SECONDS` | `0.3` | Khoảng cách giữa hai khung hình; gửi quá nhanh nhận lỗi 429. |

Firmware `firmware/esp32_cam_softap/` phục vụ ảnh chụp và trạng thái ở cổng 80 (`/capture`, `/status`), luồng MJPEG ở cổng 81 (`/stream`).

## Phạm vi chống gian lận và kiểm chứng

| Tình huống | Lớp chặn | Bằng chứng |
|---|---|---|
| Ảnh in màu khuôn mặt | MiniFASNetV2 (PAD) | E2E bước 4.3: điểm thật 0.018 < 0.45, từ chối (docs/test-report.md) |
| Ảnh tĩnh lọt qua PAD | Cổng chớp mắt EAR | E2E bước 3: "liveness: blink required"; test_liveness.py |
| Hai người cùng trong ROI | Bộ dò khuôn mặt | test_face_detector.py::test_multiple_faces_in_roi |
| Người đi ngang, khung hình rung | Cổng ổn định 3 frame, IoU ≥ 0.6 | test_pipeline.py::test_stability_resets_on_motion_and_gap |
| Mặt lạ hoặc hai ứng viên quá gần | Ngưỡng 0.52 + margin 0.05 | test_pipeline.py::test_match_threshold_and_margin |
| Điểm danh lặp lại | Ràng buộc một bản ghi/phiên | test_api.py::test_manual_attendance_duplicate_csv_and_close |

Hệ thống hiện có 97 bài kiểm thử tự động pytest và kịch bản E2E đạt 14/14 bước thành công.

### Ngoài phạm vi hiện tại

- Video phát lại có chớp mắt thật và deepfake: Chưa có lớp phòng thủ riêng; mới thử nghiệm 1 mẫu ảnh tấn công, chưa đo APCER và BPCER theo chuẩn ISO/IEC 30107-3.
- Độ chính xác nhận diện: Kịch bản E2E dùng ảnh công khai đo được khoảng cách 0.41 và 0.50 so với ngưỡng 0.52; chưa đo tỷ lệ FAR và FRR trên tập dữ liệu lớn.
- Bảo mật kênh truyền: Các luồng API và WebSocket chạy qua HTTP chưa bật mã hóa TLS; biến DEVICE_TOKEN dùng chung cho mọi camera.
- Phần cứng: Cảm biến OV2640 thu nhận kém khi gặp ngược sáng; chưa đo đạc sóng Wi-Fi và độ trễ trên mạch ESP32-CAM thực địa.

Chi tiết hướng mở rộng xem tại Chương 6 báo cáo [docs/BaoCao_BTL_IoT_Nhom05.pdf](docs/BaoCao_BTL_IoT_Nhom05.pdf).

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
- [docs/thuyet-trinh.md](docs/thuyet-trinh.md): Tóm tắt kỹ thuật và kịch bản demo khi thuyết trình.
- [docs/BaoCao_BTL_IoT_Nhom05.pdf](docs/BaoCao_BTL_IoT_Nhom05.pdf): Báo cáo tổng kết bài tập lớn của nhóm.
