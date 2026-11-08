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

## Kiến trúc & Ngăn xếp Công nghệ (Tech Stack)

```text
[Thiết bị IoT / Camera] ──(HTTP MJPEG)──> [Camera Bridge] ──(HTTP/WS)──> [FastAPI Backend]
ESP32-CAM / Webcam                        Python / LatestFrame           Python 3.12 / ASGI
                                                                                 │
               ┌─────────────────────────────────────────────────────────────────┤
               ▼                                                                 ▼
      [Pipeline AI 4 chặng]                                            [Lưu trữ & Giao diện]
YuNet ➔ Stability ➔ MiniFASNet ➔ dlib                            SQLite / WebSockets / React TS
```

| Tầng hệ thống | Công nghệ sử dụng | Vai trò & Đặc điểm chính |
| :--- | :--- | :--- |
| **Frontend (FE)** | React 18, TypeScript, Vite, CSS thuần | Giao diện Kiosk & Quản trị. Vẽ khung mặt Canvas client-side, Web Audio phát tiếng beep, WebSocket nhận diện realtime. |
| **Backend (BE)** | FastAPI (Python 3.12), Uvicorn, Pydantic | API async hiệu năng cao. Xác thực PBKDF2 (100k rounds), JWT có JTI revoke, middleware bảo mật pure ASGI, rate-limiting. |
| **Cơ sở dữ liệu (DB)** | SQLite 3, SQLAlchemy 2.0 ORM | Nhẹ, nhúng trực tiếp, write-lock `BEGIN IMMEDIATE`. Lưu vector 128D dạng JSON, so khớp Euclid cực nhanh qua NumPy. |
| **IoT & Edge Camera** | ESP32-CAM (AI-Thinker OV2640), C++ FreeRTOS | Tách cổng 80 (Snapshot/Lệnh) & 81 (Stream MJPEG). Cầu nối `camera_bridge.py` đệm khung hình mới nhất chống trôi trễ. |

## Pipeline nhận diện khuôn mặt (4 chặng nối tiếp)

1. **Phát hiện khuôn mặt**: **YuNet** (ONNX, OpenCV DNN) — Tìm bounding box $[x, y, w, h]$ và 5 mốc điểm (~15ms trên CPU). Tự động fallback sang Haar cascade nếu thiếu file.
2. **Lọc ổn định (Stability)**: Kiểm tra IoU qua $\ge 3$ khung hình liên tiếp trong vùng ROI để loại trừ rung lắc hoặc người đi lướt qua.
3. **Chống giả mạo (PAD)**: **MiniFASNetV2** (ONNX Runtime) — Phân tích vân ảnh/ánh sáng phân biệt người thật vs ảnh in/màn hình điện thoại (ngưỡng pass $\ge 0.45$). Có tùy chọn Active Liveness (chớp mắt EAR qua dlib 68 landmarks).
4. **Nhận diện danh tính**: **ResNet-34 128D (dlib)** — Trích xuất vector 128 chiều thô, so khớp khoảng cách Euclid với mẫu sinh viên của lớp (ngưỡng $\le 0.52$, margin chênh lệch với người thứ hai $\ge 0.05$).

Chi tiết các luồng xử lý và giao thức truyền tải xem tại [docs/architecture.md](docs/architecture.md).

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
   - Giao diện Kiosk và quản trị: `http://localhost:8000` (tài khoản `admin`, mật khẩu trong `.env`, mặc định `admin123456` chỉ dùng khi chạy thử trên máy cá nhân).
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
| `APP_ENV` | `development` | Môi trường triển khai (`development` hoặc `production`). Khi đặt `production`, server từ chối chạy nếu còn dùng mật khẩu hoặc token mặc định. |
| `ENABLE_API_DOCS` | `true` | Bật hoặc tắt tài liệu API Swagger/ReDoc (mặc định tự tắt khi `APP_ENV=production`). |
| `SECRET_KEY` | sinh tạm khi trống | Ký token đăng nhập HMAC; cần đặt cố định để token còn hiệu lực sau khi khởi động lại. |
| `DEVICE_TOKEN` | `esp32_device_secret_token_ptit` | Xác thực camera bridge và ESP32 gửi dữ liệu về backend. Đổi khi triển khai. |
| `ADMIN_PASSWORD` | `admin123456` | Mật khẩu đăng nhập quản trị viên trên giao diện web (mặc định chỉ dùng khi chạy thử trên máy cá nhân). Đổi khi triển khai. |
| `ADMIN_PASSWORD_HASH` | trống | Chuỗi hash PBKDF2 của mật khẩu admin; nếu đặt sẽ ưu tiên kiểm tra thay cho `ADMIN_PASSWORD` dạng rõ. |
| `LOGIN_MAX_ATTEMPTS` | `5` | Số lần thử đăng nhập sai tối đa trước khi tạm khóa 15 phút. |
| `PAD_REAL_THRESHOLD` | `0.45` | Điểm MiniFASNet tối thiểu để coi là khuôn mặt thật. |
| `RECOGNITION_THRESHOLD` | `0.52` | Ngưỡng khoảng cách Euclid để chấp nhận khớp khuôn mặt. |
| `RECOGNITION_MARGIN` | `0.05` | Chênh lệch khoảng cách tối thiểu giữa hai ứng viên gần nhất. |
| `LIVENESS_MODE` | `blink` | Kiểm tra chớp mắt (blink) hoặc tắt khi thử nghiệm (off). |
| `STABLE_FRAMES` | `3` | Số khung hình ổn định liên tiếp trước khi nhận diện. |
| `FRAME_INTERVAL_SECONDS` | `0.3` | Khoảng cách giữa hai khung hình; gửi quá nhanh nhận lỗi 429. |

Firmware `firmware/esp32_cam_softap/` phục vụ ảnh chụp và trạng thái ở cổng 80 (`/capture`, `/status`), luồng MJPEG ở cổng 81 (`/stream`).

## Chống gian lận

| Tình huống | Lớp chặn | Bằng chứng |
|---|---|---|
| Ảnh in màu khuôn mặt | MiniFASNetV2 (PAD) | E2E bước 4.3: điểm thật 0.018 < 0.45, từ chối (docs/test-report.md) |
| Ảnh tĩnh lọt qua PAD | Cổng chớp mắt EAR | E2E bước 3: "liveness: blink required"; test_liveness.py |
| Hai người cùng trong ROI | Bộ dò khuôn mặt | test_face_detector.py::test_multiple_faces_in_roi |
| Người đi ngang, khung hình rung | Cổng ổn định 3 frame, IoU ≥ 0.6 | test_pipeline.py::test_stability_resets_on_motion_and_gap |
| Mặt lạ hoặc hai ứng viên quá gần | Ngưỡng 0.52 + margin 0.05 | test_pipeline.py::test_match_threshold_and_margin |
| Điểm danh lặp lại | Ràng buộc một bản ghi/phiên | test_api.py::test_manual_attendance_duplicate_csv_and_close |

## Nhập/xuất dữ liệu

Hệ thống hỗ trợ nhập và xuất danh sách sinh viên cùng lịch học theo các định dạng CSV, XLSX (Excel) và iCalendar (.ics cho Google Calendar/Outlook). Thao tác nhập có bước xem trước, hiển thị rõ số dòng hợp lệ và chi tiết từng dòng lỗi trước khi ghi vào cơ sở dữ liệu. Mọi ô chuỗi xuất ra đều được lọc ký tự đặc biệt để chống lỗi Formula Injection trong Excel. Chi tiết và file mẫu xem tại [docs/import-export.md](docs/import-export.md).

## Bảo mật

| Biện pháp | Cơ chế thực hiện | Mục đích |
|---|---|---|
| Băm mật khẩu | PBKDF2-HMAC-SHA256 (600.000 vòng) | Bảo vệ thông tin xác thực quản trị viên, chống lộ mật khẩu dạng rõ |
| Giới hạn thử sai | Bộ đếm trong RAM theo IP + tài khoản | Chặn tấn công dò mật khẩu (trả về mã 429 sau 5 lần sai) |
| Thu hồi phiên | Mã định danh token ngẫu nhiên (jti) | Hỗ trợ đăng xuất và vô hiệu hóa token ngay lập tức trên máy chủ |
| Header an toàn | CSP, X-Frame-Options, nosniff, no-store | Chống tấn công clickjacking, MIME sniffing và lưu cache dữ liệu nhạy cảm |
| Khóa cấu hình | Kiểm tra tham số an toàn khi khởi động | Từ chối chạy môi trường production nếu còn để lộ mật khẩu hoặc token mặc định |

Chi tiết các biện pháp và hướng dẫn kiểm tra xem tại [docs/security.md](docs/security.md).

## Kiểm thử

```bash
PYTHONPATH=backend pytest backend/tests -q
```

176 passed; E2E 14/14 bước. Chi tiết: [docs/test-report.md](docs/test-report.md).

## Tài liệu

- [Báo cáo BTL (PDF)](docs/BaoCao_BTL_IoT_Nhom05.pdf)
- [Kiến trúc](docs/architecture.md)
- [ESP32-CAM SoftAP](docs/camera-softap.md)
- [Docker](docs/docker.md)
- [Đánh giá mô hình](docs/model-evaluation.md)
- [Kiểm thử](docs/test-report.md)
- [Kịch bản thuyết trình](docs/thuyet-trinh.md)
- [Nhập/xuất dữ liệu](docs/import-export.md)
- [Bảo mật hệ thống](docs/security.md)
