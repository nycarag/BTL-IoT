# Hệ Thống Điểm Danh Sinh Viên AIoT

Sinh viên đứng trước ESP32-CAM, hệ thống nhận ra khuôn mặt, loại ảnh giả, rồi ghi điểm danh vào đúng ca học đang mở. Camera chỉ chụp và phát hình; toàn bộ AI chạy trên máy chủ FastAPI, kết quả hiện ngay trên màn hình kiosk React.

## Hệ thống làm được gì

| Việc | Cách làm | Mã nguồn |
|---|---|---|
| Điểm danh bằng khuôn mặt | ESP32-CAM phát MJPEG, máy chủ chạy 4 chặng: tìm mặt, lọc ổn định, chống giả mạo, so khớp danh tính trong lớp | `backend/app/api/attendance.py` |
| Chống điểm danh hộ | MiniFASNetV2 loại ảnh in và màn hình điện thoại; tùy chọn bắt chớp mắt (EAR) | `backend/app/services/antispoof.py`, `liveness.py` |
| Ca điểm danh theo lịch học | Nhập thời khóa biểu `.ics`, đến giờ ca tự mở, hết giờ tự đóng và ghi vắng; lịch đang trong giờ thì ca mở ngay khi lưu | `backend/app/services/auto_session.py`, `session_lifecycle.py` |
| Đi muộn | Tính từ giờ bắt đầu buổi học, ngưỡng mặc định 15 phút, đổi trên giao diện và tự tính lại bản ghi cũ | `backend/app/api/settings.py` |
| Kiosk thời gian thực | Hình camera qua WebSocket, khung mặt 4 màu theo trạng thái, tiếng bíp khi điểm danh xong | `frontend/src/KioskView.tsx` |
| Quản trị | Sinh viên, lớp, buổi học, thiết bị và vùng nhận diện (ROI), xác minh thủ công, nhật ký xác thực, nhật ký quản trị | `frontend/src/App.tsx` |
| Nhập và xuất dữ liệu | Sinh viên và lịch học qua CSV, XLSX, iCalendar; có bước xem trước, báo lỗi theo từng dòng | `backend/app/api/roster_io.py`, `schedules.py` |
| Bảo mật | Băm mật khẩu PBKDF2, khóa đăng nhập sai, thu hồi token, header an toàn, từ chối cấu hình yếu ở production | `backend/app/core/security.py` |

Số đo ngày 11/11/2026 trên máy demo (máy ảo 2 CPU), chi tiết ở [docs/test-report.md](docs/test-report.md):

- 215 bài kiểm thử tự động đều đạt; kịch bản đầu-cuối 14/14 bước.
- Lưu một lịch đang trong giờ học, ca điểm danh mở sau khoảng 20 ms.
- Trong lúc nhận diện, máy chủ vẫn trả lời dưới 30 ms ở 1096/1096 lần đo. Trước khi tách bước trích vector khuôn mặt sang tiến trình riêng, 17/923 lần bị trễ khoảng 75 ms.

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
| **Backend (BE)** | FastAPI (Python 3.12), Uvicorn, Pydantic | API async. Mật khẩu băm PBKDF2 (600.000 vòng), token có `jti` để thu hồi, middleware header bảo mật, giới hạn thử đăng nhập. Trích vector khuôn mặt chạy ở tiến trình con. |
| **Cơ sở dữ liệu (DB)** | SQLite 3, SQLAlchemy 2.0 ORM | Nhúng trực tiếp, chế độ WAL, khóa ghi `BEGIN IMMEDIATE`. Lưu vector 128D dạng JSON, so khớp Euclid bằng NumPy. |
| **IoT & Edge Camera** | ESP32-CAM (AI-Thinker OV2640), C++ FreeRTOS | Bắt hotspot, tự phát Wi-Fi dự phòng khi không nối được. Cổng 80 cho ảnh chụp, trạng thái và lệnh chỉnh cảm biến (`/capture`, `/status`, `/control`); cổng 81 cho luồng MJPEG. Cầu nối `camera_bridge.py` chỉ giữ khung hình mới nhất để hình không trôi trễ. |

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
3. Khởi chạy hệ thống 1-Click:
   ```bash
   ./run_one_click.sh
   ```
   Hệ thống tự động kích hoạt môi trường ảo, khởi chạy backend FastAPI tại cổng 8000, mở trình duyệt vào giao diện Kiosk và cho phép chọn nguồn camera (ESP32-CAM hoặc Webcam laptop).
4. Truy cập giao diện:
   - Giao diện Kiosk và quản trị: `http://localhost:8000` (tài khoản `admin`, mật khẩu trong `.env`, mặc định `admin123456` chỉ dùng khi chạy thử trên máy cá nhân).
   - Tài liệu API Swagger: `http://localhost:8000/docs`.
5. Kết nối camera:
   - Qua Web UI: Vào tab Thiết bị & vùng điểm danh, chọn bật camera laptop hoặc ESP32-CAM.
   - Qua script: Chạy `./start_esp32.sh` để kết nối ESP32-CAM qua Wi-Fi (tự động áp cấu hình QVGA + Quality 16 siêu mượt), hoặc chạy `./start_webcam.sh` để dùng webcam laptop.
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
| `LIVENESS_MODE` | `blink` | `blink`: ngoài MiniFASNetV2 còn bắt chớp mắt (EAR). Giá trị khác, ví dụ `passive`: chỉ dùng MiniFASNetV2 trên một khung hình. Buổi demo đặt `passive`. |
| `AUTO_SESSION_ENABLED` | `true` | Bật tiến trình nền tự động mở và đóng ca điểm danh theo lịch học. Lịch đang trong giờ học thì ca mở ngay khi lưu. |
| `AUTO_SESSION_INTERVAL_SECONDS` | `30` | Chu kỳ quét của tiến trình nền trên (5 đến 300 giây). |
| `RECOGNITION_PROCESS` | `true` | Trích vector khuôn mặt trong tiến trình con, để luồng camera không khựng lúc nhận diện. |
| `LATE_AFTER_MINUTES` | `15` | Ngưỡng tính đi muộn (phút); có thể chỉnh động trực tiếp trên giao diện web. |
| `STABLE_FRAMES` | `3` | Số khung hình ổn định liên tiếp trước khi nhận diện. Buổi demo đặt `1`. |
| `FRAME_INTERVAL_SECONDS` | `0.3` | Khoảng cách tối thiểu giữa hai khung hình gửi vào mô hình AI. |

Firmware chính nằm ở `firmware/esp32_cam/` (bắt hotspot, có Wi-Fi tự phát dự phòng). `firmware/esp32_cam_softap/` là bản chỉ tự phát Wi-Fi, giữ lại để dự phòng.

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

215 passed; E2E 14/14 bước. Bộ test dùng CSDL tạm và không đọc `.env`, nên chạy được trên máy đang chứa dữ liệu thật. Chi tiết: [docs/test-report.md](docs/test-report.md).

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
