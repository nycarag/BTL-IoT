# Kết quả kiểm thử phần mềm

## Đã thực hiện

- Ngày 2026-11-04: `PYTHONPATH=backend pytest backend/tests -q`: **97 passed, 3 warnings** trong môi trường Python kiểm thử Linux ngoài Docker.
- `python -m compileall`: mã Python app/tests/seed/evaluate_pad/camera_bridge qua kiểm tra cú pháp.
- Frontend `tsc -b && vite build`: PASS trong bản sao kiểm thử trên filesystem Linux (dependency trên /mnt/d từng bị hỏng).
- `docker compose --profile camera-ap config --quiet`: PASS; chỉ kiểm tra cấu hình, **không build/chạy container** theo yêu cầu người dùng.
- MiniFASNetV2 ONNX thật đã nạp được, input `batch_size × 3 × 80 × 80`. Chưa đo độ chính xác thực tế.

| Nhóm | Kiểm thử đã có |
|---|---|
| API/auth | Bearer bắt buộc, sai mật khẩu/token thiết bị, WebSocket không auth bị đóng |
| CRUD | Mã SV trùng/normalize, lớp không tồn tại, sửa hồ sơ, không xóa lớp/hồ sơ có lịch sử |
| Enrollment | Consent bắt buộc, lưu/thu hồi embedding, không lưu ảnh thô (encode được mock) |
| Attendance | Đúng lớp, phiên mở/đóng, chống trùng, đi muộn, manual có audit, CSV |
| AI pipeline | Chờ nhiều frame, PAD reject/lỗi fail-closed, output NaN/label thật/calibrated, preprocessing BGR đúng |
| WebSocket | Auth hợp lệ, nhận liveness/attendance và session close |
| Device/ROI | ROI trái/phải không hợp lệ, TTL offline, image format/dimensions |
| SoftAP bridge | Camera failure không heartbeat; idle/active; multipart giữ JPEG binary; chỉ tin accepted của backend; reload config |
| Camera latency | MJPEG chia chunk, bộ đệm latest-only/stale, AI không kéo lùi video, WebSocket binary/ACK bỏ backlog, auth camera socket |
| Camera preview | Auth bắt buộc, preview không attendance, ảnh không cache, thiếu ảnh/TTL/capacity và không ghi đè kết quả frame mới bằng frame cũ |
| Domain/report | ROI, normalize dấu, roster duplicate, filename ambiguous, CSV formula neutralization, APCER/BPCER arithmetic |

Trong bài kiểm thử lỗi AI cố ý, server log `RuntimeError: model failed` là mock có chủ đích; assertion xác nhận không ghi attendance và test PASS. Các ca AI accepted/embedding đều mock, **không chứng minh mô hình nhận đúng người/chống ảnh giả**.

## Chưa thực hiện / cần ghi số liệu khi chạy thực

| Kịch bản thực tế | Kết quả mong đợi | Trạng thái |
|---|---|---|
| Firmware AI Thinker mới biên dịch/nạp | SoftAP hoặc STA đúng chế độ | Chưa có board/Arduino CLI trong phiên |
| Laptop nối Wi-Fi ESP32, /capture | JPEG ổn định, bridge forward | Camera đang ở máy khác; chưa kiểm tra mạng thực |
| Docker images/runtime | Build/chạy healthy, WS proxy, volume persist | Người dùng tự build/chạy |
| Người thật đã đăng ký | Nhận đúng khi đủ điều kiện | Chưa có dữ liệu consent để đo |
| Người ngoài ROI/nhiều mặt/thoáng qua/mờ | Không ghi | Logic có; chưa đo camera thật |
| Ảnh in/video phát điện thoại | PAD reject với tỷ lệ đo được | Chưa đo APCER/BPCER |
| Người chưa đăng ký/giống nhau | Reject với FAR/FRR đo được | Chưa đo |
| Mất camera/mạng | Offline sau TTL, không success giả | Unit test có; chưa thử phần cứng |
| Tốc độ laptop/ESP32 | Latency phù hợp interval/tracking gap | Chưa benchmark |

Thu thập calibration và held-out test độc lập theo model-evaluation.md. Ghi camera, ánh sáng, attack type, số mẫu, threshold, APCER/BPCER, FAR/FRR và latency. Không tuyên bố chống giả mạo tuyệt đối hoặc biến kết quả unit test thành kết quả đo AI.

---

# Kiểm thử E2E 11/2026: Kiểm thử đầu-cuối trên backend thật với dữ liệu ảnh thực tế

* **Thời điểm thực hiện:** 03/11/2026
* **Môi trường:** Máy chủ FastAPI chạy qua Uvicorn thật trên cổng 8765, SQLite database độc lập tại thư mục tạm, kết nối mạng HTTP/WebSocket nội bộ (localhost).
* **Nguồn dữ liệu hình ảnh:** 
  > [!IMPORTANT]
  > Toàn bộ các ảnh sử dụng trong đợt kiểm thử này là **ảnh công khai** (ảnh chân dung chụp từ web công khai của hai cựu Tổng thống Mỹ Barack Obama và Joe Biden, và ảnh mẫu tấn công in màu `image_F1.jpg` từ bộ dữ liệu mở của nhóm Minivision AI). Đợt kiểm thử này **không sử dụng camera phần cứng ESP32-CAM thực tế** mà nạp trực tiếp qua HTTP REST và WebSocket.

### Bảng kết quả kiểm thử đầu-cuối (E2E)

| Bước kiểm thử | Kỳ vọng | Thực tế đo được | Kết quả |
|---|---|---|---|
| **1. Admin Login** | Trả về status 200 kèm bearer token ký HMAC hợp lệ khi cung cấp đúng thông tin xác thực admin | Status 200, cấp bearer token ký HMAC thành công | **PASS** |
| **2.1 Tạo lớp học** | `POST /api/classes` tạo lớp mới mã `E2E_CLASS`, trả về status 201 kèm ID | Status 201, tạo thành công `ClassRoom` (ID=1, Code='E2E_CLASS') | **PASS** |
| **2.2 Tạo sinh viên** | `POST /api/students` tạo 2 sinh viên `SV_OBAMA` và `SV_BIDEN`, trả về status 201 | Status 201, tạo thành công `SV_OBAMA` (ID=1) và `SV_BIDEN` (ID=2) | **PASS** |
| **2.3 Đăng ký khuôn mặt SV_OBAMA (đa mẫu)** | `POST /api/students/{id}/face` nhận 2 ảnh (`obama.jpg` + `obama2.jpg`), trích xuất vector dlib 128D, lưu mảng đa mẫu thô | Status 200, `enrolled=True`, `samples=2`, `raw_image_stored=False` | **PASS** |
| **2.4 Đăng ký khuôn mặt SV_BIDEN (đơn mẫu)** | `POST /api/students/{id}/face` nhận 1 ảnh (`biden.jpg`), trích xuất vector dlib 128D | Status 200, `enrolled=True`, `samples=1`, `raw_image_stored=False` | **PASS** |
| **2.5 Tạo & mở phiên điểm danh** | `POST /api/sessions` tạo phiên, sau đó `POST .../start` kích hoạt phiên sang trạng thái `open` | Status 200, `AttendanceSession` ID=1 chuyển sang trạng thái `open` | **PASS** |
| **2.6 Heartbeat thiết bị** | `POST /api/devices/heartbeat` kèm `X-Device-Token` và `X-Device-Id` đăng ký thiết bị online | Status 200, `Device` `esp32-cam-e2e` chuyển sang trạng thái `online` | **PASS** |
| **2.7 Gán thiết bị vào phiên** | `PUT /api/devices/{id}/config` gán session_id và ROI toàn khung hình (0..1) | Status 200, `active=True`, `session_id=1` | **PASS** |
| **3. Liveness Blink Gate (`LIVENESS_MODE=blink`)** | Gửi 3 frame liên tiếp ảnh `obama_cif.jpg` qua `POST /api/devices/{id}/frames`: 2 frame đầu chờ ổn định (`waiting for stable face`), frame thứ 3 đạt chuẩn ổn định nhưng chưa có chớp mắt trên luồng preview $\rightarrow$ từ chối với lý do `liveness: blink required` | - Frame 1: `accepted=False`, reason=`waiting for stable face`<br>- Frame 2: `accepted=False`, reason=`waiting for stable face`<br>- Frame 3: `accepted=False`, reason=`liveness: blink required` | **PASS** |
| **4.1 Điểm danh SV_OBAMA (`LIVENESS_MODE=off`)** | Khởi động lại backend với `LIVENESS_MODE=off`: gửi 3 frame `obama_cif.jpg`, frame thứ 3 nhận diện thành công sinh viên `SV_OBAMA` | - Frame 1, 2: `waiting for stable face`<br>- Frame 3: `accepted=True`, `created=True`, `student_code='SV_OBAMA'`, `student_name='Barack Obama'` | **PASS** |
| **4.2 Điểm danh SV_BIDEN (`LIVENESS_MODE=off`)** | Gửi 3 frame `biden.jpg`, frame thứ 3 nhận diện thành công sinh viên `SV_BIDEN` | - Frame 1, 2: `waiting for stable face`<br>- Frame 3: `accepted=True`, `created=True`, `student_code='SV_BIDEN'`, `student_name='Joe Biden'` | **PASS** |
| **4.3 Chống giả mạo PAD (ảnh `image_F1.jpg`)** | Gửi 3 frame ảnh in giả mạo `image_F1.jpg` (Minivision spoof): mô hình MiniFASNet phát hiện tấn công và từ chối | - Frame 1, 2: `waiting for stable face`<br>- Frame 3: `accepted=False`, reason=`spoof or uncertain PAD score`, `pad_score=0.01797` (< ngưỡng pass 0.45) | **PASS** |
| **5. Luồng WebSocket Camera (`/ws/devices/{id}/camera`)** | Client WebSocket xác thực Bearer token, nhận metadata JSON ban đầu; server nhận preview frame từ HTTP POST và đẩy binary JPEG xuống WebSocket; client gửi ACK `"next"` | Kết nối thành công, nhận meta payload ban đầu, nhận binary JPEG (64.962 bytes) và gửi ACK `"next"` ổn định | **PASS** |
| **6. Xuất báo cáo điểm danh CSV (`/api/attendance/export`)** | `GET /api/attendance/export?session_id=1` trả về tệp CSV mã hóa UTF-8 chứa đầy đủ 2 bản ghi điểm danh | Status 200, trả về dữ liệu CSV hợp lệ chứa đầy đủ thông tin `SV_OBAMA` và `SV_BIDEN` | **PASS** |

### Chi tiết tệp CSV xuất khẩu thực tế

```csv
Mã sinh viên,Họ và tên,Thời gian,Trạng thái,Phương thức,Thiết bị
SV_OBAMA,Barack Obama,2026-11-03 13:15:47,present,"face+pad:0.9999;distance:0.5001",esp32-cam-e2e
SV_BIDEN,Joe Biden,2026-11-03 13:15:48,present,"face+pad:0.9999;distance:0.4102",esp32-cam-e2e
```

---

# Bổ sung 11/2026: nhập/xuất dữ liệu và bảo mật

* **Thời điểm kiểm tra:** 07/11/2026.
* **Môi trường:** Python 3.12.16 (virtualenv), FastAPI qua Uvicorn, SQLite database độc lập tại `/tmp/btl_scratch`.
* **Kết quả bộ kiểm thử tự động (pytest):**
  - Lệnh chạy: `PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q`
  - Kết quả: **176 passed, 1 warning** trong 15.76s.
  - So với baseline (97 passed): Toàn bộ 97 bài kiểm thử ban đầu giữ nguyên trạng thái pass, bổ sung 79 bài kiểm thử mới cho các tính năng bảo mật, kiểm toán, nhập/xuất bảng tính và lịch học.
* **Biên dịch giao diện (Frontend):**
  - Lệnh chạy: `cd frontend && npx tsc -p tsconfig.app.json --noEmit && npm run build`
  - Kết quả: PASS, không phát sinh lỗi TypeScript. Bundle production đồng bộ hoàn toàn với mã nguồn.

### Bảng kết quả kiểm tra trực tiếp qua HTTP REST và Socket (cổng 8011)

| Kịch bản kiểm tra | Yêu cầu kỹ thuật | Kết quả thực tế | Mã HTTP | Đánh giá |
|---|---|---|:---:|:---:|
| **4a. Chống dò mật khẩu** | Đăng nhập sai liên tiếp 5 lần với cùng tên người dùng | 4 lần đầu trả 401; lần 5 trả 429 kèm tiêu đề `Retry-After: 900` | **429** | **PASS** |
| **4b. Xem trước & áp dụng sinh viên** | Nạp `docs/samples/sinh_vien_mau.csv` chế độ preview rồi commit (`create_missing_classes=true`) | Trả về JSON tổng kết tạo 5 sinh viên, tự tạo lớp `D23CTAT01-B` | **200** | **PASS** |
| **4b. Xuất bảng sinh viên** | Tải danh sách dạng XLSX và CSV | File XLSX đọc qua openpyxl có đủ 6 dòng (1 tiêu đề + 5 dòng sinh viên); file CSV có byte đầu `\xef\xbb\xbf` (BOM UTF-8) | **200** | **PASS** |
| **4c. Nhập lịch học** | Nạp `docs/samples/lich_hoc_mau.csv` chế độ commit cho lớp đã tạo | Tạo thành công 6 bản ghi lịch học | **200** | **PASS** |
| **4c. Xuất iCalendar & tạo buổi** | Tải lịch dạng `.ics`; gọi tạo buổi điểm danh từ lịch | `app.services.ics.parse_calendar` trích xuất đúng 6 sự kiện giờ Việt Nam (ICT); tạo phiên điểm danh mới ID=1 ở trạng thái `draft` | **200 / 201** | **PASS** |
| **4d. Tiêu đề bảo mật HTTP** | Kiểm tra tiêu đề tại `GET /` và `GET /api/students` | Trang chủ có `Content-Security-Policy` và `X-Frame-Options: DENY`; endpoint dữ liệu có `Cache-Control: no-store` | **200** | **PASS** |
| **4e. Nhật ký quản trị** | Truy vấn danh sách kiểm toán tại `GET /api/audit-logs` | Ghi nhận đầy đủ 8 loại hành vi: `auth.login`, `auth.login_failed`, `auth.login_locked`, `students.import`, `students.export`, `schedules.import`, `schedules.export`, `schedules.create_session` | **200** | **PASS** |
| **4f. Đăng xuất & thu hồi token** | Gọi `POST /api/auth/logout` và tái sử dụng token | Đăng xuất trả 204 No Content; dùng lại token bị từ chối truy cập | **204 / 401** | **PASS** |
| **4g. Kiểm tra tệp rác & dung lượng** | Gửi tệp `.xlsx` hỏng cấu trúc và tệp dung lượng 3 MiB | Tệp hỏng trả lỗi tiếng Việt "Tệp Excel hỏng hoặc không đúng định dạng .xlsx" (máy chủ không crash); tệp vượt ngưỡng trả "Dung lượng tệp vượt quá 2 MiB" | **422 / 413** | **PASS** |
| **4h. Chặn cấu hình yếu ở production** | Chạy ứng dụng với `APP_ENV=production` và tham số mặc định | Máy chủ phát sinh `RuntimeError` cảnh báo secret/mật khẩu yếu và dừng khởi động | **N/A (Chặn khởi động)** | **PASS** |

