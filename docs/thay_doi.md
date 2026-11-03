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
