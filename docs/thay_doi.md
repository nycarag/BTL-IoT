# Nhật Ký Thay Đổi Mã Nguồn (Changelog)

## Task T01: Bảo Mật Cơ Bản (CORS, Token Secret Key, Form Login, Audio Subprocess)

* **Ngày thực hiện:** 03/11/2026
* **Nhánh git:** `overhaul/v2`

### Danh sách tệp thay đổi

| Tệp tin | Nội dung thay đổi | Lý do kỹ thuật |
|---|---|---|
| `backend/app/core/config.py` | Thêm `cors_origin_regex` (mặc định cho phép localhost, 127.0.0.1 và các dải IP riêng LAN: 10.x, 172.16-31.x, 192.168.x trên mọi port) và `secret_key` nạp từ biến môi trường `SECRET_KEY` (tự động sinh ngẫu nhiên `secrets.token_hex(32)` và cảnh báo nếu chưa đặt). | Khắc phục cấu hình CORS mở toang trước đây; tách biệt khóa ký token sinh trắc học khỏi mật khẩu quản trị viên. |
| `backend/app/main.py` | Bỏ `allow_origin_regex=".*"`, thay thế bằng `settings.cors_origin_regex or None`. Vẫn giữ `allow_origins=list(settings.cors_origins)`. | Ngăn chặn các website độc hại bên ngoài gửi request có kèm thông tin xác thực (CORS credentials leak). |
| `backend/app/core/security.py` | Đổi cơ chế ký và kiểm tra chữ ký token trong `_signature` và `verify_token` từ `settings.admin_password` sang `settings.secret_key`. | Đảm bảo nguyên tắc bảo mật: mật khẩu dùng để xác thực đăng nhập, secret key dùng để ký token phiên làm việc. |
| `backend/app/services/audio_service.py` | Thay thế chuỗi lệnh shell `os.system` bằng hàm `_try_play` dùng `subprocess.run` với danh sách tham số (không bật `shell=True`). Giữ nguyên thứ tự ưu tiên backend âm thanh: `pw-play` -> `paplay` -> `aplay`. | Loại bỏ nguy cơ command injection và lỗi thực thi qua shell `/bin/sh`, vẫn đảm bảo chạy bất đồng bộ trong background thread. |
| `backend/.env.example` | Bổ sung biến mẫu `SECRET_KEY` và `CORS_ORIGIN_REGEX`. | Hướng dẫn cấu hình môi trường đầy đủ cho việc triển khai máy chủ. |
| `frontend/src/App.tsx` | Xóa `defaultValue="admin123456"` ở ô nhập mật khẩu đăng nhập, giữ nguyên `defaultValue="admin"`. | Tránh để lộ mật khẩu quản trị viên mặc định ngay trên giao diện web. |
| `backend/tests/test_api.py` | Bổ sung 2 bài kiểm thử: `test_cors_origin_filtering` (xác nhận origin `http://evil.com` bị từ chối header CORS, origin IP LAN `http://192.168.4.2:5173` và `localhost` được chấp nhận) và `test_token_with_different_key_rejected` (xác nhận token ký bằng khóa khác bị trả về mã 401). | Kiểm chứng tự động hành vi bảo mật mới được bổ sung. |

### Kết quả kiểm thử thực tế

1. **Backend Unit Tests:**
   * Lệnh: `PYTHONPATH=backend pytest backend/tests -q`
   * Kết quả: **44 passed in 10.54s** (toàn bộ 42 bài test cũ và 2 bài test bảo mật mới đều PASS).
2. **Frontend TypeScript & Build:**
   * Lệnh: `npx tsc -b && vite build`
   * Kết quả: **0 lỗi TypeScript**, build bundle production thành công (không đưa thư mục `dist` vào commit).

## Task T02: Sửa Lỗi Đồng Thời (Thread-Safety) Trong Pipeline Điểm Danh & Dọn Dẹp Rate-Limit

* **Ngày thực hiện:** 03/11/2026
* **Nhánh git:** `overhaul/v2`

### Danh sách tệp thay đổi

| Tệp tin | Nội dung thay đổi | Lý do kỹ thuật |
|---|---|---|
| `backend/app/services/face_recognition.py` | 1. Tách hàm thuần `match(probe, references, threshold=None, margin=None) -> RecognitionResult \| None` không dính dáng đến I/O hoặc cơ sở dữ liệu.<br>2. Cập nhật `FaceRecognitionAdapter.recognize` để trích xuất probe vector rồi truy vấn database và ủy quyền so khớp cho `match()`. | Tách biệt tính toán so khớp vector thuần túy khỏi truy vấn cơ sở dữ liệu, cho phép tái sử dụng hàm so khớp an toàn trên luồng bất đồng bộ. |
| `backend/app/api/attendance.py` | 1. Trong `_process_frame`: tách bước tính vector embedding `probe = await run_in_threadpool(lambda: rec.encode(body, detection.box))` (thuần CPU) ra khỏi truy vấn cơ sở dữ liệu. Thực hiện truy vấn `references` trên luồng request chính và gọi hàm thuần `match(probe, references)`. Hỗ trợ tương thích ngược cho mock test `recognize`.<br>2. Đoạn rate-limit: thay thế `last_frames.clear()` (xóa sạch mọi camera khi vượt quá 256) bằng cơ chế lọc và chỉ loại bỏ các bản ghi cũ hơn 60 giây (`now - t > 60`). | Tránh lỗi tranh chấp đồng thời (race condition / crash) khi đối tượng SQLAlchemy `Session` (`db`) bị chuyển giao và truy cập đồng thời trong worker thread pool; bảo vệ kiểm soát tần suất của các thiết bị vừa gửi frame, không bị xóa sạch vết khi dung lượng bảng rate-limit đạt ngưỡng. |
| `backend/tests/test_pipeline.py` | Thêm 4 bài unit test:<br>1. `test_match_empty_and_invalid_probe`: Kiểm tra probe rỗng, None, sai kích thước (64-dim) hoặc chứa NaN đều trả về `None`.<br>2. `test_match_invalid_references_ignored`: Kiểm tra các mẫu khuôn mặt tham chiếu hỏng (JSON sai cú pháp, kích thước sai, chứa NaN/Inf) đều bị bỏ qua an toàn không gây lỗi.<br>3. `test_match_threshold_and_margin`: Kiểm tra chính xác logic ngưỡng khoảng cách (`recognition_threshold`) và độ tin cậy biên (`recognition_margin`).<br>4. `test_rate_limit_cleanup_preserves_recent_devices`: Kiểm tra cơ chế eviction chỉ xóa các thiết bị cũ quá 60s, bảo toàn nguyên vẹn dấu vết tần suất của các thiết bị mới gửi frame. | Đảm bảo tính đúng đắn và phòng ngừa hồi quy cho logic so khớp vector và quản lý tần suất khung hình. |

### Kết quả kiểm thử thực tế

1. **Backend Unit Tests:**
   * Lệnh: `PYTHONPATH=backend /tmp/claude-1000/-home-nycarag/a5456080-ab66-4d8b-a6cf-843b3c5e2231/scratchpad/venv/bin/python -m pytest backend/tests -q`
   * Kết quả: **48 passed in 15.88s** (toàn bộ 44 bài test trước đó + 4 bài unit test mới cho T02 đều PASS).
