# Tài liệu kiến trúc an toàn và bảo mật hệ thống

Tài liệu này mô tả mô hình mối đe dọa, các biện pháp kỹ thuật đã hiện thực trong mã nguồn, hướng dẫn triển khai an toàn và các rủi ro kỹ thuật còn lại của hệ thống điểm danh khuôn mặt AIoT (nycarag/BTL-IoT).

---

## 1. Tài sản cần bảo vệ

Hệ thống quản lý 5 nhóm tài sản chính:

1. **Dữ liệu cá nhân sinh viên**: Bao gồm họ tên, mã sinh viên (MSSV), ngày sinh và lớp học. Dữ liệu này lưu trong bảng `students` và `classes` của SQLite.
2. **Dữ liệu sinh trắc học (vector khuôn mặt)**: Mảng số thực 128 chiều trích xuất từ khuôn mặt qua mô hình nhận diện khuôn mặt, lưu dưới dạng JSON mảng đa mẫu tại bảng `face_references`. Đây là dữ liệu nhạy cảm nhất của hệ thống.
3. **Bản ghi điểm danh**: Trạng thái tham gia buổi học (đúng giờ, đi muộn), mốc thời gian ghi nhận, mã thiết bị và phương thức xác thực (`face+pad:...` hoặc `manual:...`), lưu tại bảng `attendance` và `attendance_sessions`.
4. **Quyền quản trị hệ thống**: Token xác thực Bearer token cấp cho tài khoản quản trị viên, cho phép truy cập toàn bộ các endpoint cấu hình thiết bị, tạo/đóng buổi học, quản lý sinh viên, lịch học và xem nhật ký kiểm toán.
5. **Luồng dữ liệu ảnh từ camera**: Dữ liệu ảnh chụp snapshot và luồng video truyền từ ESP32-CAM hoặc webcam về dịch vụ backend để phát hiện, kiểm tra thực thể sống và nhận diện.

---

## 2. Mô hình mối đe dọa và biện pháp kiểm soát

Bảng dưới đây tổng hợp các mối đe dọa an toàn thông tin, biện pháp kiểm soát kỹ thuật tương ứng, vị trí cài đặt trong mã nguồn và trường hợp kiểm thử tự động đã bao phủ:

| STT | Mối đe dọa | Biện pháp kiểm soát kỹ thuật | Vị trí trong mã nguồn | Kiểm thử bằng test nào |
| :--- | :--- | :--- | :--- | :--- |
| 1 | **Dò mật khẩu quản trị (Brute-force / Credential Stuffing)** | Bộ giới hạn tốc độ `LoginThrottle` trong RAM theo cặp `(client_ip, username)`. Sai quá 5 lần trong 300 giây sẽ khóa 900 giây, trả về HTTP 429 kèm header `Retry-After`. Hashing mật khẩu bằng thuật toán PBKDF2-HMAC-SHA256 (600.000 vòng lặp) kèm salt ngẫu nhiên 16 bytes. | `backend/app/core/security.py:LoginThrottle`, `hash_password`, `verify_password`, `check_admin_password`<br>`backend/app/api/auth.py:login` | `backend/tests/test_auth_security.py:test_login_throttling_and_rate_limiting`<br>`backend/tests/test_auth_security.py:test_hash_and_verify_password`<br>`backend/tests/test_auth_security.py:test_admin_password_hash_login` |
| 2 | **Lộ token / Chiếm đoạt phiên (Token theft & replay)** | Token có định dạng `username:expiry:jti` ký bằng HMAC-SHA256 với khóa `SECRET_KEY`. Endpoint `POST /api/auth/logout` thu hồi token bằng cách đưa định danh `jti` vào danh sách đen `_revoked` trong bộ nhớ cho đến khi hết hạn TTL (8 giờ). `verify_token` từ chối token hết hạn, sai chữ ký, token thiếu jti hoặc token đã bị thu hồi. | `backend/app/core/security.py:issue_token`, `revoke_token`, `verify_token`<br>`backend/app/api/auth.py:logout` | `backend/tests/test_auth_security.py:test_logout_and_token_revocation`<br>`backend/tests/test_auth_security.py:test_old_format_token_rejected`<br>`backend/tests/test_auth_security.py:test_websocket_auth_with_new_token` |
| 3 | **Giao diện bị nhúng lừa đảo (Clickjacking)** | Gửi header `X-Frame-Options: DENY` và chỉ thị CSP `frame-ancestors 'none'` trên mọi phản hồi HTTP từ cả ASGI middleware lẫn cấu hình Nginx reverse proxy. | `backend/app/core/middleware.py:SecurityHeadersMiddleware`<br>`frontend/nginx.conf` | `backend/tests/test_security_headers.py:test_html_response_has_csp_and_security_headers` |
| 4 | **Tấn công Cross-Site Scripting (XSS)** | Header `Content-Security-Policy` khóa nguồn thực thi script (`default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'`); Header `X-Content-Type-Options: nosniff`. Toàn bộ giao diện React sử dụng JSX rendering tự động escape ký tự, không dùng `dangerouslySetInnerHTML`. | `backend/app/core/middleware.py:SecurityHeadersMiddleware`<br>`frontend/nginx.conf`<br>`frontend/src/` (toàn bộ component React) | `backend/tests/test_security_headers.py:test_html_response_has_csp_and_security_headers`<br>`backend/tests/test_security_headers.py:test_api_json_response_has_nosniff_and_no_store_without_csp` |
| 5 | **Chèn mã công thức độc hại (CSV/Excel Formula Injection)** | Hàm `escape_cell` kiểm tra mọi ô chuỗi khi xuất tệp CSV/XLSX. Nếu chuỗi bắt đầu bằng các ký tự nguy hiểm (`=`, `+`, `-`, `@`) hoặc khoảng trắng/tab/CR dẫn đến ký tự nguy hiểm, hệ thống tự động thêm dấu nháy đơn `'` ở đầu để vô hiệu hóa thực thi công thức trong phần mềm bảng tính. | `backend/app/services/tabular.py:escape_cell`, `write_csv`, `write_xlsx` | `backend/tests/test_tabular.py:test_escape_cell`<br>`backend/tests/test_tabular.py:test_write_csv`<br>`backend/tests/test_roster_io.py:test_export_formula_injection_escaping`<br>`backend/tests/test_pipeline.py:test_csv_formula_is_neutralized` |
| 6 | **Tấn công XML Bomb / Zip Bomb qua tệp Excel .xlsx** | Sử dụng gói `defusedxml` để phòng chống thực thể mở rộng XML độc hại. Tệp `.xlsx` được mở qua thư viện `openpyxl` với cờ `read_only=True, data_only=True`. Kiểm tra giới hạn dung lượng trước khi phân tích cấu trúc zip. | `backend/app/services/tabular.py:_iter_xlsx_rows`, `read_table` | `backend/tests/test_tabular.py:test_limits_max_rows_and_max_bytes_and_cols`<br>`backend/tests/test_tabular.py:test_unsupported_extension_and_bad_xlsx` |
| 7 | **Tải lên tệp dung lượng quá lớn gây cạn kiệt tài nguyên (DoS)** | Kiểm tra kích thước stream tệp upload: tệp danh sách sinh viên và lịch học giới hạn tối đa 2 MiB + 1 byte (`UploadFile.read(2097153)`), vượt quá trả về HTTP 413. Giới hạn xử lý tối đa 30 cột và 2000 dòng dữ liệu (HTTP 422). Ảnh đăng ký khuôn mặt giới hạn tối đa 5 MiB/ảnh và không quá 5 ảnh một lần gửi. | `backend/app/services/tabular.py:read_table`<br>`backend/app/api/roster_io.py:import_students`<br>`backend/app/api/schedules.py:import_schedules`<br>`backend/app/api/students.py:enroll_face` | `backend/tests/test_roster_io.py:test_file_size_extension_and_auth_guards`<br>`backend/tests/test_schedules.py:test_import_file_too_large_returns_413`<br>`backend/tests/test_tabular.py:test_limits_max_rows_and_max_bytes_and_cols` |
| 8 | **Sử dụng cấu hình mặc định không an toàn** | Hàm `enforce_secure_settings` quét cấu hình lúc khởi động: kiểm tra mật khẩu mặc định `admin123456`, token thiết bị mặc định `esp32_device_secret_token_ptit`, `SECRET_KEY` ngắn hơn 32 ký tự, hoặc bật API docs ở môi trường production. Khi `APP_ENV=production`, hệ thống ném `RuntimeError` và dừng khởi động nếu phát hiện cấu hình yếu. | `backend/app/main.py:insecure_settings`, `enforce_secure_settings`, `create_app` | `backend/tests/test_api.py:test_app_creation` |
| 9 | **Lộ thông tin API qua tài liệu Swagger / OpenAPI** | Tự động tắt Swagger UI (`/docs`), ReDoc (`/redoc`) và đặc tả OpenAPI (`/openapi.json`) khi `APP_ENV=production` hoặc `ENABLE_API_DOCS=false` bằng cách gán các route này về `None`. | `backend/app/main.py:_is_docs_enabled`, `create_app` | `backend/tests/test_security_headers.py:test_swagger_docs_has_no_csp` |
| 10 | **Lưu đệm dữ liệu cá nhân sinh viên trên trình duyệt hoặc proxy** | Tự động gắn header `Cache-Control: no-store` cho toàn bộ các phản hồi API dưới đường dẫn `/api/*` thông qua ASGI middleware và cấu hình Nginx location block. | `backend/app/core/middleware.py:SecurityHeadersMiddleware`<br>`frontend/nginx.conf:location /api/` | `backend/tests/test_security_headers.py:test_api_json_response_has_nosniff_and_no_store_without_csp` |
| 11 | **Giả mạo thiết bị camera gửi bản tin điểm danh** | Endpoint gửi heartbeat và dữ liệu camera bắt buộc xác thực qua header `X-Device-Token` và `X-Device-Id`. Token được so sánh hằng thời gian (`hmac.compare_digest`). Thiết bị phải gửi heartbeat định kỳ; nếu mất tín hiệu quá 60 giây, trạng thái tự chuyển sang offline. | `backend/app/core/security.py:verify_device_token`<br>`backend/app/api/devices.py:heartbeat` | `backend/tests/test_camera_bridge.py:test_heartbeat_requires_token` |
| 12 | **Tấn công giả mạo khuôn mặt bằng ảnh in hoặc video phát lại (Spoofing)** | Tích hợp mạng nơ-ron MiniFASNetV2 (ONNX) phân loại ảnh thật/giả với ngưỡng xác suất Real ≥ 0.45, kết hợp cơ chế kiểm tra thực thể sống chủ động (Active Liveness qua chỉ số EAR bằng 68 landmarks mắt của dlib). Điểm danh chỉ hợp lệ khi phát hiện chớp mắt trong vòng 5 giây gần nhất, và trạng thái chớp mắt được tiêu thụ ngay sau đó để chống phát lại. | `backend/app/services/pipeline.py:AttendancePipeline`<br>`backend/app/services/antispoof.py`<br>`backend/app/services/liveness.py:LivenessTracker` | `backend/tests/test_liveness.py:test_synthetic_series_open_closed_open_detects_blink`<br>`backend/tests/test_liveness.py:test_consume_blink`<br>`backend/tests/test_liveness.py:test_pipeline_gate_rejects_when_blink_not_detected`<br>`backend/tests/test_pipeline.py:test_pad_missing_and_nan_fail_closed` |
| 13 | **Thao tác quản trị không thể truy vết (Lack of audit trail)** | Ghi nhận chi tiết mọi hành động nghiệp vụ vào bảng `audit_logs` (thời gian, người thực hiện, loại hành động, đối tượng tác động, dữ liệu chi tiết, địa chỉ IP). Bao gồm đăng nhập, đăng xuất, xuất/nhập sinh viên, tạo/sửa/xóa lịch học, tạo buổi điểm danh. Tuyệt đối không ghi mật khẩu hay token vào trường detail. Endpoint `GET /api/audit-logs` chỉ cho phép đọc, có xác thực admin. | `backend/app/services/audit.py:log_action`, `client_ip`<br>`backend/app/models/school.py:AuditLog`<br>`backend/app/api/audit.py:list_audit_logs` | `backend/tests/test_auth_security.py:test_audit_log_records_without_password`<br>`backend/tests/test_audit_api.py:test_list_all_audit_logs_order_desc`<br>`backend/tests/test_audit_api.py:test_read_only_endpoint`<br>`backend/tests/test_roster_io.py:test_audit_log_after_import_commit` |

---

## 3. Hướng dẫn cấu hình triển khai an toàn

Khi triển khai hệ thống lên máy chủ thực tế hoặc môi trường thử nghiệm chính thức, người quản trị cần thực hiện tuần tự các bước cấu hình sau:

### 3.1. Tạo khóa bí mật hệ thống (SECRET_KEY)

Khóa ký phiên đăng nhập phải là một chuỗi ngẫu nhiên có độ dài tối thiểu 32 byte (64 ký tự hex). Tạo khóa bằng lệnh:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Sao chép giá trị sinh ra và gán vào biến môi trường `SECRET_KEY` trong tệp `.env`.

### 3.2. Tạo mã băm mật khẩu quản trị (ADMIN_PASSWORD_HASH)

Không lưu mật khẩu quản trị dạng văn bản rõ (`ADMIN_PASSWORD`). Sử dụng module bảo mật tích hợp sẵn trong mã nguồn để sinh chuỗi băm chuẩn PBKDF2:

```bash
cd backend && python3 -m app.core.security
```

Nhập mật khẩu quản trị mới và xác nhận theo hướng dẫn trên màn hình. Lệnh sẽ xuất ra chuỗi dạng:

```text
pbkdf2_sha256$600000$xxxxxxxxxxxx$yyyyyyyyyyyy
```

Sao chép toàn bộ chuỗi này và gán vào biến `ADMIN_PASSWORD_HASH` trong tệp `.env`, đồng thời xóa bỏ hoặc để trống biến `ADMIN_PASSWORD`.

### 3.3. Thiết lập cờ môi trường sản xuất và tắt tài liệu API

Thêm hoặc cập nhật các biến sau trong tệp `.env`:

```env
APP_ENV=production
ENABLE_API_DOCS=false
```

Khi đặt `APP_ENV=production`, hệ thống sẽ kích hoạt hàm `enforce_secure_settings`. Nếu phát hiện bất kỳ cấu hình mặc định nào chưa được đổi, dịch vụ backend sẽ lập tức dừng hoạt động và báo lỗi cụ thể ra console.

### 3.4. Đổi mã bí mật của thiết bị (DEVICE_TOKEN)

Sinh chuỗi token ngẫu nhiên tối thiểu 16 ký tự để làm mã định danh liên lạc giữa camera và máy chủ:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(24))"
```

Cập nhật giá trị này vào biến `DEVICE_TOKEN` trong `.env` của backend, đồng thời nạp cùng giá trị này vào firmware của bo mạch ESP32-CAM.

### 3.5. Cô lập cổng lắng nghe dịch vụ backend (BACKEND_BIND)

Khi triển khai cùng Nginx reverse proxy hoặc qua Docker Compose, cổng dịch vụ FastAPI (mặc định 8000) không được mở công khai ra Internet hoặc mạng ngoài. Cấu hình trong `.env`:

```env
BACKEND_BIND=127.0.0.1
BACKEND_PORT=8000
```

Toàn bộ lưu lượng từ bên ngoài chỉ được phép đi qua Nginx tại cổng web (ví dụ 8080 hoặc 443).

---

## 4. Các rủi ro kỹ thuật còn lại và hướng xử lý đề xuất

Dưới đây là các hạn chế kỹ thuật hiện hữu trong phiên bản hiện tại cùng phương án đề xuất khắc phục cho các giai đoạn nâng cấp tiếp theo. Các phương án này được ghi nhận rõ ràng dưới dạng **đề xuất**, hiện tại hệ thống chưa cài đặt:

1. **Một DEVICE_TOKEN dùng chung cho toàn bộ camera**:
   - *Hiện trạng*: Mọi bo mạch camera ESP32-CAM và tiến trình bridge kết nối vào hệ thống đều dùng chung một mã `DEVICE_TOKEN`. Nếu một thiết bị phần cứng bị chiếm đoạt và trích xuất bộ nhớ flash, mã token dùng chung này có thể bị lộ để gửi dữ liệu giả cho các camera khác.
   - *Đề xuất chưa làm*: Cấp phát token định danh riêng biệt cho từng thiết bị theo địa chỉ MAC/Hardware ID, hoặc thiết lập xác thực hai chiều mTLS (Mutual TLS) giữa thiết bị và server.

2. **ESP32-CAM gửi luồng ảnh qua HTTP không mã hóa trong mạng SoftAP**:
   - *Hiện trạng*: Bo mạch ESP32-CAM phát Wi-Fi SoftAP hoặc kết nối Wi-Fi cục bộ truyền gói tin snapshot JPEG qua HTTP (cổng 80) không có mã hóa TLS. Kẻ tấn công nếu bắt được gói tin sóng Wi-Fi có thể xem được dữ liệu hình ảnh truyền qua mạng.
   - *Đề xuất chưa làm*: Cấu hình mạng Wi-Fi bảo vệ bằng WPA2/WPA3 với mật khẩu mạnh; nghiên cứu tối ưu bộ nhớ ESP32 để hỗ trợ HTTPS hoặc đóng gói luồng dữ liệu qua kênh truyền mã hóa VPN/WireGuard nhẹ.

3. **Một tài khoản quản trị duy nhất, chưa phân quyền vai trò (RBAC)**:
   - *Hiện trạng*: Hệ thống chỉ hỗ trợ một tài khoản `admin`. Giảng viên, trợ giảng và quản trị viên phòng máy phải dùng chung tài khoản này, gây khó khăn cho việc phân định trách nhiệm cá nhân trong nhật ký kiểm toán.
   - *Đề xuất chưa làm*: Thiết kế bảng người dùng `users`, bảng vai trò `roles` (Admin, Giảng viên, Trợ giảng), phân chia quyền hạn chi tiết trên từng API endpoint và hỗ trợ tích hợp hệ thống xác thực tập trung (SSO/OAuth2/LDAP) của nhà trường.

4. **Danh sách thu hồi token và bộ đếm đăng nhập sai lưu trong bộ nhớ RAM**:
   - *Hiện trạng*: Cả biến `_revoked` (danh sách jti đã logout) và `login_throttle` (bộ đếm brute-force) đều lưu trong biến bộ nhớ cục bộ của tiến trình Python. Dữ liệu này sẽ mất khi tiến trình backend restart. Đồng thời, nếu chạy Uvicorn với nhiều worker tiến trình độc lập, bộ nhớ này không được chia sẻ đồng bộ giữa các worker.
   - *Đề xuất chưa làm*: Đưa danh sách blacklist token và rate-limiting key sang dịch vụ lưu trữ dữ liệu tập trung tốc độ cao như Redis với cơ chế tự động hết hạn key (TTL).

5. **CORS cho phép toàn bộ dải IP mạng cục bộ (LAN)**:
   - *Hiện trạng*: Biểu thức chính quy `DEFAULT_CORS_ORIGIN_REGEX` chấp nhận mọi origin từ các dải IP riêng tư (`192.168.x.x`, `10.x.x.x`, `172.16-31.x.x`) để thuận tiện cho việc phát triển và thử nghiệm qua nhiều thiết bị trong mạng lab. Điều này có thể bị lợi dụng nếu có thiết bị lạ hoạt động trong cùng mạng LAN.
   - *Đề xuất chưa làm*: Khi triển khai sản xuất, bắt buộc khóa chặt biến `CORS_ORIGINS` với các tên miền hoặc IP xác định rõ ràng, loại bỏ regex mở tự do cho mạng nội bộ.

6. **Vector khuôn mặt lưu dưới dạng văn bản rõ trong SQLite**:
   - *Hiện trạng*: Cột `FaceReference.embedding` lưu trực tiếp mảng JSON chứa các số thực 128 chiều mà chưa được mã hóa ở tầng lưu trữ (Encryption at-rest). Bất kỳ ai có quyền truy cập trực tiếp vào tệp `attendance.db` đều có thể đọc được dữ liệu đặc trưng này.
   - *Đề xuất chưa làm*: Áp dụng giải pháp mã hóa cơ sở dữ liệu (SQLCipher) hoặc mã hóa đối xứng AES-256-GCM cho riêng cột embedding trước khi ghi xuống đĩa, khóa mã hóa được quản lý độc lập ngoài cơ sở dữ liệu.

7. **Kịch bản chạy start.sh chưa có lớp mã hóa HTTPS**:
   - *Hiện trạng*: Script phát triển cục bộ `start.sh` chạy FastAPI và Frontend qua HTTP thuần trên cổng 8000 và 5173.
   - *Đề xuất chưa làm*: Bắt buộc cấu hình chứng chỉ TLS/SSL trên Nginx hoặc proxy biên khi đưa vào vận hành thực tế; kích hoạt header `Strict-Transport-Security` (HSTS).

---

## 5. Bảo vệ dữ liệu cá nhân sinh viên

Dữ liệu hình ảnh và vector khuôn mặt là dữ liệu sinh trắc học, thuộc nhóm dữ liệu cá nhân nhạy cảm. Hệ thống thiết lập các nguyên tắc bảo vệ sau:

1. **Sự đồng ý rõ ràng (Biometric Consent)**:
   - Thao tác đăng ký khuôn mặt sinh viên (`POST /api/students/{student_id}/face`) bắt buộc phải gửi cờ `consent: bool = True`.
   - Nếu không có xác nhận đồng ý từ sinh viên, mã nguồn kiểm tra tại `backend/app/api/students.py:enroll_face` sẽ lập tức ném lỗi HTTP 422: `"Explicit biometric consent is required"`.

2. **Ngăn chặn rò rỉ dữ liệu sinh trắc trong quá trình xuất dữ liệu**:
   - Toàn bộ các API xuất danh sách sinh viên (`/api/students/export`) và xuất lịch học (`/api/schedules/export`) tuyệt đối không bao gồm cột chứa vector embedding hay liên kết dữ liệu thô khuôn mặt.
   - Chỉ xuất trường hiển thị trạng thái `Đã đăng ký khuôn mặt` dưới dạng văn bản Có/Không để phục vụ công tác đối soát nghiệp vụ của giảng viên.

3. **Tuân thủ quy định pháp luật Việt Nam**:
   - Hoạt động thu thập, phân tích, xử lý và lưu trữ dữ liệu nhận diện khuôn mặt sinh viên trong dự án này cần đối chiếu trực tiếp với các văn bản pháp luật hiện hành tại Việt Nam, đặc biệt là **Nghị định 13/2023/NĐ-CP về bảo vệ dữ liệu cá nhân**.
   - Các đơn vị áp dụng thực tế có trách nhiệm tham chiếu chi tiết các quy định hiện hành về quyền của chủ thể dữ liệu, biện pháp bảo vệ kỹ thuật và lập hồ sơ đánh giá tác động xử lý dữ liệu cá nhân theo đúng hướng dẫn của cơ quan nhà nước có thẩm quyền.
