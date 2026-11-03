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

### Rework T02: Xóa Hack Mock Production, Chuẩn Hóa Signature Match và Xóa Method Thừa

* **Ngày thực hiện:** 03/11/2026
* **Nội dung thay đổi:**
  * `backend/app/api/attendance.py`: Xóa bỏ hoàn toàn `from unittest.mock import Mock` và nhánh rẽ kiểm tra mock trong code production; pipeline điểm danh chỉ còn duy nhất 1 luồng chuẩn: `probe = await run_in_threadpool(rec.encode, body, detection.box)` -> truy vấn `rows` trong DB trên luồng request -> gọi hàm thuần `match(probe, rows)`.
  * `backend/app/services/face_recognition.py`: Rút gọn chữ ký `match(probe, rows: list[tuple[FaceReference, Student]], threshold=None, margin=None)`, bỏ duck-typing thừa; xóa bỏ hoàn toàn method không còn sử dụng `FaceRecognitionAdapter.recognize()`.
  * `backend/tests/test_api.py`: Chuyển đổi test kiểm thử điểm danh từ mock `recognize` sang mock `rec.encode` trả về vector 128 chiều + tạo bản ghi `FaceReference` hợp lệ 128 chiều trong DB test, kiểm tra hành vi thực tế 100% của toàn bộ pipeline.
* **Kết quả kiểm thử thực tế:**
  * Lệnh: `PYTHONPATH=backend /tmp/claude-1000/-home-nycarag/a5456080-ab66-4d8b-a6cf-843b3c5e2231/scratchpad/venv/bin/python -m pytest backend/tests -q`
  * Kết quả: **48 passed in 12.77s**.

## Task T03: Sửa Bất Nhất Vector Đặc Trưng (Bỏ L2-Norm Enrollment) & Hỗ Trợ Đa Mẫu Tham Chiếu

* **Ngày thực hiện:** 03/11/2026
* **Nhánh git:** `overhaul/v2`

### Danh sách tệp thay đổi

| Tệp tin | Nội dung thay đổi | Lý do kỹ thuật |
|---|---|---|
| `backend/app/api/students.py` | Khi enroll ảnh khuôn mặt: bỏ việc tính trung bình và chia chuẩn L2-norm (`norm = np.linalg.norm; avg_vec = avg_vec / norm`); lưu toàn bộ danh sách vector thô của 1..N ảnh vào `FaceReference.embedding` dưới dạng JSON list-of-lists `[[128 số], ...]`. | Khắc phục sai lệch thang đo nghiêm trọng giữa vector thô lúc nhận diện (dlib norm ~1.36-1.39) và vector đã chuẩn hóa L2 lúc đăng ký (norm = 1.0); bảo toàn đặc trưng đa góc nhìn. |
| `backend/seed.py` | Cập nhật logic tự động sinh vector khuôn mặt từ thư mục `data/faces/`: lưu toàn bộ danh sách vector thô dưới dạng JSON list-of-lists thay vì lấy trung bình rồi chia L2-norm. | Đồng bộ chuẩn lưu trữ embedding trên toàn hệ thống. |
| `backend/app/services/face_recognition.py` | 1. Trong `match()`: với mỗi sinh viên có nhiều mẫu ảnh ($M \times 128$), tính khoảng cách Euclid vector hóa bằng numpy (`np.linalg.norm(arr - probe, axis=1)`) và lấy khoảng cách nhỏ nhất `min_dist` đại diện cho sinh viên đó.<br>2. So sánh ngưỡng và margin giữa sinh viên top 1 và sinh viên top 2 (đảm bảo margin tính giữa 2 sinh viên khác nhau, không phạt margin giữa 2 mẫu của cùng một người).<br>3. Tương thích ngược: nếu embedding cũ là 1-D (128 số) thì coi là 1 mẫu; ghi log WARNING 1 lần nếu vector có norm $\approx 1.0$ (phát hiện vector chuẩn hóa L2 cũ). | Tối ưu độ chính xác nhận diện đa góc mặt, hỗ trợ tương thích ngược dữ liệu cũ và cảnh báo chuẩn hóa L2. |
| `backend/tests/test_pipeline.py` | Thêm 3 bài unit test:<br>1. `test_match_multi_sample_reference`: kiểm tra sinh viên có nhiều mẫu ảnh, hệ thống lấy đúng mẫu có khoảng cách nhỏ nhất.<br>2. `test_match_legacy_1d_and_warning`: kiểm tra dữ liệu 1-D legacy cũ vẫn khớp bình thường và phát ra log WARNING.<br>3. `test_margin_between_different_students_not_within_same_student`: kiểm tra 2 mẫu gần nhau của cùng 1 sinh viên không kích hoạt vi phạm margin; chỉ vi phạm khi 2 sinh viên khác nhau có khoảng cách quá sát nhau (< margin). | Kiểm chứng tự động toàn diện thuật toán so khớp đa mẫu. |
| `backend/tests/test_workflows.py` | Thêm test `test_enrollment_multiple_images_stores_list_of_lists`: kiểm tra endpoint upload 2 ảnh và xác thực cơ sở dữ liệu lưu trữ đúng định dạng list-of-lists 2 phần tử 128 chiều. | Đảm bảo tính toàn vẹn của API đăng ký khuôn mặt nhiều ảnh. |
| `docs/model-evaluation.md` | Bổ sung mục đánh giá thực nghiệm nhận diện trên ảnh thật từ repo chuẩn `ageitgey/face_recognition` (`obama.jpg`, `obama2.jpg`, `biden.jpg`), đo lường norm thô thực tế và ma trận khoảng cách Euclid thật. | Cung cấp bằng chứng thực nghiệm rõ ràng, minh bạch cho hệ thống nhận diện. |

### Kết quả kiểm thử thực tế

1. **Backend Unit Tests:**
   * Lệnh: `PYTHONPATH=backend /tmp/claude-1000/-home-nycarag/a5456080-ab66-4d8b-a6cf-843b3c5e2231/scratchpad/venv/bin/python -m pytest backend/tests -q`
   * Kết quả: **52 passed in 12.46s** (toàn bộ 48 bài test trước đó + 4 bài unit test mới cho T03 đều PASS).
2. **Đo nghiệm ảnh thật (`scratchpad/work/eval_real_faces.py`):**
   * Cặp cùng người (`obama.jpg` $\leftrightarrow$ `obama2.jpg`): khoảng cách **0.3457** (< ngưỡng 0.60).
   * Cặp khác người (`obama.jpg` $\leftrightarrow$ `biden.jpg`): khoảng cách **0.8402** (> ngưỡng 0.60).
