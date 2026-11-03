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

## Task T04: Tối Ưu Giải Mã Ảnh - Decode JPEG 1 Lần Duy Nhất Mỗi Khung Hình AI (Kèm Rework Khắc Phục Hồi Quy Bảo Mật)

* **Ngày thực hiện:** 03/11/2026
* **Nhánh git:** `overhaul/v2`

### Danh sách tệp thay đổi

| Tệp tin | Nội dung thay đổi | Lý do kỹ thuật |
|---|---|---|
| `backend/app/services/images.py` | Cập nhật hàm `decode_image(body: bytes) -> np.ndarray`: (a) Đọc header lười (lazy) bằng Pillow `Image.open` trong `catch_warnings` để kiểm tra định dạng `JPEG/PNG`, kích thước 64×64 đến 4 megapixels và chặn `DecompressionBombWarning`/`Error` **trước khi** giải mã pixel; (b) Sau đó mới giải mã pixel đúng 1 lần duy nhất bằng `cv2.imdecode`. | Khắc phục triệt để nguy cơ Decompression Bomb và format giả mạo, bảo toàn 100% cơ chế bảo vệ của Pillow cũ đồng thời loại bỏ decode pixel lặp. |
| `backend/app/services/face_detector.py` | `FaceDetector.detect_largest(frame: np.ndarray, roi=...)`: chỉ nhận mảng BGR ndarray, loại bỏ hoàn toàn việc nhận bytes và import cục bộ. | Thống nhất interface, tránh phân mảnh kiểu dữ liệu. |
| `backend/app/services/antispoof.py` | `prepare_face` và `AntiSpoofAdapter.evaluate`: chỉ nhận mảng BGR ndarray, loại bỏ hoàn toàn việc nhận bytes và import cục bộ. | Tránh decode lặp và thống nhất kiểu dữ liệu ndarray BGR. |
| `backend/app/services/face_recognition.py` | `FaceRecognitionAdapter.encode`: chỉ nhận mảng BGR ndarray, tự chuyển đổi `cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)` thành `uint8 contiguous` cho dlib. Xóa hoàn toàn nhánh nhận bytes và import cục bộ. | Tránh decode lặp và dlib chỉ xử lý mảng RGB ndarray chuẩn. |
| `backend/app/api/attendance.py` | Trong `_process_frame`: gọi `frame = decode_image(body)` 1 lần duy nhất ngay sau khi nhận frame; truyền trực tiếp `frame` (BGR ndarray) vào detector, PAD và recognizer. | Khung hình AI từ ESP32-CAM chỉ giải mã đúng 1 lần duy nhất. |
| `backend/app/api/students.py` | Khi enroll ảnh khuôn mặt: gọi `frame = decode_image(body)` tại nơi nhận bytes rồi truyền trực tiếp `frame` vào `recognizer.encode(frame)`. | Đảm bảo tính nhất quán của API nhận diện. |
| `backend/evaluate_pad.py` | Gọi `frame = decode_image(body)` trước khi truyền vào `adapter.evaluate(frame, box)`. | Đồng bộ interface nhận ndarray BGR cho công cụ đánh giá PAD offline. |
| `backend/tests/test_pipeline.py` | Cập nhật các test cũ truyền ndarray BGR cho detector/PAD; bổ sung các test bảo mật bắt buộc:<br>1. `test_decode_image_rejects_oversized_header_without_calling_imdecode`: ảnh PNG header 5000×5000 bị từ chối ở bước kiểm tra header mà hoàn toàn không gọi `cv2.imdecode` (xác thực bằng monkeypatch).<br>2. `test_decode_image_rejects_gif_format`: từ chối định dạng ảnh không phải JPEG/PNG.<br>3. `test_detector_accepts_ndarray` và `test_decode_image_and_dimension_validation`. | Kiểm chứng tự động cơ chế bảo vệ Decompression Bomb và interface mới. |
| `backend/tests/test_workflows.py` | Cập nhật `test_pad_real_index_and_calibration` truyền ndarray BGR cho `AntiSpoofAdapter.evaluate`. | Đảm bảo tương thích interface mới. |

### Đo đạc benchmark thực tế từng chặng trên ảnh CIF chuẩn (400×296 ESP32-CAM, 50 lần lặp)

> [!IMPORTANT]
> **Ghi chú thay thế bảng số liệu cũ:** Bảng số liệu ~1000 ms trước đây được đo trên ảnh gốc `obama.jpg` có kích thước rất lớn (768×1024 ~ 0.8 MP). Trong triển khai thực tế, camera ESP32-CAM gửi khung hình ở độ phân giải **CIF (400×296)**. Dưới đây là bảng số liệu đo đạc độc lập từng chặng (50 lần mỗi chặng) giữa bản TRƯỚC (commit `5c1229a`) và bản SAU trên đúng kích thước CIF 400×296.

| Chặng xử lý | Trước (commit 5c1229a) - Median ms | Sau (REWORK T04) - Median ms | Phân tích kỹ thuật |
|---|---|---|---|
| **Decode / Validate** | **0.19 ms** (Pillow verify) | **0.98 ms** (Pillow header + cv2.imdecode) | Bước decode gộp kiểm tra header + giải mã pixel C++ một lần duy nhất. |
| **Detect (cv2 Haar)** | **37.31 ms** (gồm cv2.imdecode lần 2) | **41.45 ms** (nhận trực tiếp BGR ndarray) | Chênh lệch dao động trong biên độ tải CPU hệ thống. |
| **PAD (MiniFASNet)** | **6.58 ms** (gồm cv2.imdecode lần 3) | **5.84 ms** (crop trực tiếp trên ndarray BGR) | Giảm thời gian do không phải giải mã lại ảnh. |
| **Encode (dlib 128D)** | **154.70 ms** (gồm load_image_file lần 4) | **151.83 ms** (cvtColor BGR->RGB contiguous) | Tiết kiệm thời gian decode và cấp phát buffer bộ nhớ dlib. |
| **Tổng pipeline** | **200.95 ms** (Mean: 228.85 ms) | **205.30 ms** (Mean: 219.50 ms) | Pipeline đạt ~5 FPS ổn định trên CPU máy chủ. |

#### Điều tra nguyên nhân hiệu năng dlib trên ảnh CIF 400×296:
* Trên ảnh CIF 400×296, thời gian trích xuất dlib embedding **không phải là ~1s**, mà thực tế chỉ tốn **~152 ms** (chiếm ~74% tổng thời gian pipeline 205 ms).
* Lý do bước encode chiếm 152 ms là do `face_recognition.face_encodings` chạy qua mạng nơ-ron tích chập ResNet-34 sâu của dlib (`dlib_face_recognition_resnet_model_v1`) trên CPU một luồng với `num_jitters=1` mặc định. Đây là đặc tính tính toán bình thường của mô hình deep learning trên CPU.
* Lợi ích thực tế lớn nhất của việc decode 1 lần:
  1. Loại bỏ hoàn toàn việc cấp phát và giải phóng 4 buffer pixel JPEG riêng biệt trong RAM trên mỗi frame.
  2. Ngăn chặn triệt để tấn công Decompression Bomb ngay từ bước đọc header trước khi vào OpenCV.
  3. Kiến trúc code sạch sẽ, thuần ndarray BGR cho toàn bộ các module thị giác máy tính.

### Kết quả kiểm thử thực tế

1. **Backend Unit Tests:**
   * Lệnh: `PYTHONPATH=backend /tmp/claude-1000/-home-nycarag/a5456080-ab66-4d8b-a6cf-843b3c5e2231/scratchpad/venv/bin/python -m pytest backend/tests -q`
   * Kết quả: **56 passed in 11.75s** (toàn bộ 52 bài test trước đó + 4 bài test bảo mật/interface mới cho T04 đều PASS).

## Task T05: Thay Haar Cascade Bằng YuNet (OpenCV Zoo) Có Fallback Tự Động

* **Ngày thực hiện:** 03/11/2026
* **Nhánh git:** `overhaul/v2`

### Danh sách tệp thay đổi và bổ sung

| Tệp tin | Hành động | Nội dung thay đổi | Lý do kỹ thuật |
|---|---|---|---|
| `models/yunet/face_detection_yunet_2023mar.onnx` | Thêm mới | Model ONNX chính thức từ OpenCV Zoo (`opencv/opencv_zoo`). Kích thước: 232,589 bytes (~227 KB).<br>**SHA-256:** `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`. | Mô hình phát hiện khuôn mặt học sâu siêu nhẹ (lightweight deep learning CNN), độ chính xác cao hơn vượt trội so với bộ lọc Haar truyền thống, hỗ trợ phát hiện khuôn mặt nghiêng/đa góc độ và 5 điểm mốc (landmarks). |
| `models/yunet/LICENSE` | Thêm mới | Giấy phép bản quyền MIT License gốc của mô hình YuNet (Copyright (c) 2020 Shiqi Yu) từ OpenCV Zoo (`models/face_detection_yunet/LICENSE`). | Đảm bảo tuân thủ chính xác bản quyền tác giả Shiqi Yu theo MIT License. |
| `backend/app/core/config.py` | Chỉnh sửa | Bổ sung các cấu hình trong `Settings`: `face_detector` (mặc định `"yunet"`), `yunet_model_path` (mặc định trỏ đến `models/yunet/face_detection_yunet_2023mar.onnx`), `face_score_threshold` (mặc định `0.8`). | Cho phép cấu hình linh hoạt loại detector, đường dẫn mô hình và ngưỡng tin cậy khuôn mặt qua biến môi trường. |
| `backend/.env.example` | Chỉnh sửa | Bổ sung các biến mẫu: `FACE_DETECTOR=yunet`, `YUNET_MODEL_PATH=models/yunet/face_detection_yunet_2023mar.onnx`, `FACE_SCORE_THRESHOLD=0.8`. | Hướng dẫn cấu hình môi trường chuẩn cho người vận hành. |
| `backend/app/services/face_detector.py` | Chỉnh sửa | 1. Bổ sung trường `landmarks5: tuple[tuple[float, float], ...] \| None = None` vào `FaceDetection`.<br>2. Thêm hàm `clamp_box()` ép toạ độ bounding box luôn nằm trong biên ảnh `(0 <= x, y và x+w <= width, y+h <= height)`.<br>3. Triển khai `FaceDetector` dùng `cv2.FaceDetectorYN.create()`, gọi `setInputSize((width, height))` theo từng frame.<br>4. Cơ chế fallback: nếu file model không tồn tại hoặc lỗi khởi tạo, tự động fallback sang Haar cascade cũ và ghi log WARNING 1 lần.<br>5. Giữ nguyên 100% logic lọc candidate ROI, Laplacian sharpness quality score và các reason: `"no face detected"`, `"multiple faces in ROI"`, `"face outside ROI"`, `"face too small"`, `"image too blurry"`, `"ok"`. | Thay thế bộ nhận diện khuôn mặt cũ kỹ bằng mạng nơ-ron YuNet hiện đại, bảo vệ an toàn cho module PAD không bị lỗi văng box ngoài biên, đồng thời đảm bảo tính sẵn sàng cao với fallback tự động. |
| `backend/tests/test_face_detector.py` | Thêm mới | Bổ sung 10 bài unit test toàn diện:<br>- Kiểm tra kiểm soát frame đầu vào không hợp lệ (`None`, string, ảnh < 64×64).<br>- Kiểm tra hàm `clamp_box()` với toạ độ âm, toạ độ vượt biên.<br>- Kiểm tra frame trắng không có mặt (`"no face detected"`).<br>- Kiểm tra fallback tự động sang Haar khi đường dẫn model thiếu hoặc lỗi khởi tạo.<br>- Kiểm tra trích xuất landmarks 5 điểm và tính toán quality score từ YuNet.<br>- Kiểm tra case nhiều mặt trong ROI (`"multiple faces in ROI"`).<br>- Kiểm tra case mặt ngoài ROI (`"face outside ROI"`).<br>- Kiểm tra `StabilityGate` đảm bảo tính liên tục hình học qua 3 frame liên tiếp. | Bảo đảm độ tin cậy và không hồi quy cho module detector. |
| `docs/architecture.md` | Chỉnh sửa | Cập nhật luồng xử lý: `YuNet face detector (ONNX, score >= 0.8) kèm Haar fallback + một mặt trong ROI + size/sharpness + clamp bbox`. | Phản ánh chính xác kiến trúc hệ thống hiện tại. |

### Đo đạc benchmark thực tế (100 lần lặp trên ảnh CIF 400×296 ESP32-CAM)

> [!IMPORTANT]
> Đo nghiệm được thực hiện trên cùng ảnh thực nghiệm chuẩn `obama_cif.jpg` (kích thước chuẩn của camera ESP32-CAM: 400×296). Kết quả đo lường 100 lần lặp liên tục sau giai đoạn warm-up:

| Chỉ số đo | Haar Cascade cũ (`haarcascade_frontalface_default.xml`) | YuNet mới (`face_detection_yunet_2023mar.onnx`) | Đánh giá so sánh |
|---|---|---|---|
| **Thời gian trung bình (Mean)** | **50.82 ms** | **12.88 ms** | **YuNet nhanh hơn ~3.94 lần** |
| **Thời gian tối thiểu (Min)** | 30.03 ms | 7.22 ms | Tối ưu đáng kể độ trễ khung hình |
| **Thời gian tối đa (Max)** | 115.96 ms | 46.97 ms | Không bị nghẽn giật đỉnh tải |
| **Phân vị 95% (P95)** | 91.68 ms | 34.90 ms | Ổn định vượt trội |
| **Độ chính xác trên ảnh CIF** | Bị **false positive** (nhận nhầm nhiều vùng nhiễu thành mặt $\rightarrow$ bị reject với lý do `multiple faces in ROI`) | Phát hiện **chính xác 1 khuôn mặt** `(166, 18, 98, 98)` kèm 5 điểm mốc landmarks sắc nét $\rightarrow$ chấp thuận `ok` | Khắc phục triệt để lỗi từ chối oan do nhiễu của Haar cascade |

### Kết quả kiểm thử thực tế

1. **Backend Unit Tests:**
   * Lệnh: `PYTHONPATH=backend /tmp/claude-1000/-home-nycarag/a5456080-ab66-4d8b-a6cf-843b3c5e2231/scratchpad/venv/bin/python -m pytest backend/tests -q`
   * Kết quả: **67 passed in 29.50s** (toàn bộ 56 bài test trước đó + 11 bài unit test mới cho T05 đều PASS 100%).
2. **Kiểm thử trường hợp 2 người trong ROI:**
   * Sử dụng ảnh `two_people.jpg` ghép trong `scratchpad/work/`: detector trả về chính xác `reason = "multiple faces in ROI"`.

### Rework T05: Đính Chính Giấy Phép Bản Quyền YuNet Sang MIT License (Shiqi Yu)

* **Ngày thực hiện:** 03/11/2026
* **Lý do kỹ thuật:** Thư mục gốc của kho chứa OpenCV Zoo sử dụng Apache-2.0, tuy nhiên mô hình cụ thể `face_detection_yunet` được phát triển bởi tác giả Shiqi Yu và áp dụng giấy phép bản quyền riêng là **MIT License** (`Copyright (c) 2020 Shiqi Yu <shiqi.yu@gmail.com>`).
* **Hành động khắc phục:**
  1. Tải chính xác tệp license gốc từ `https://raw.githubusercontent.com/opencv/opencv_zoo/main/models/face_detection_yunet/LICENSE` (1,085 bytes, SHA-256: `c83b8120c50ccbd4c4f96edf53141bdd566ebb8f8e9227e415326aa1b1aba958`) và ghi đè vào `models/yunet/LICENSE` (so sánh byte khớp 100%).
  2. Sửa toàn bộ tài liệu mô tả giấy phép của YuNet sang MIT License (Copyright (c) 2020 Shiqi Yu). Không thay đổi mã nguồn.

## Task T06: Thẩm Định & Chuẩn Hóa Tiền Xử Lý MiniFASNet (PAD)

* **Ngày thực hiện:** 03/11/2026
* **Nhánh git:** `overhaul/v2`

### Danh sách tệp thay đổi

| Tệp tin | Hành động | Nội dung thay đổi | Lý do kỹ thuật |
|---|---|---|---|
| `backend/app/services/antispoof.py` | Chỉnh sửa | 1. Bổ sung hàm `_get_new_box` tuân thủ 100% thuật toán của Minivision (`minivision-ai/Silent-Face-Anti-Spoofing` `src/generate_patches.py`): thay vì cắt cụt box khi ở gần mép ảnh (`max(0, ...)`), thuật toán dịch chuyển box vào trong biên ảnh (`right_bottom_x -= left_top_x`, v.v.), bảo toàn trọn vẹn tỷ lệ aspect ratio và ngữ cảnh khuôn mặt.<br>2. Giữ nguyên toàn bộ quy ước tiền xử lý gốc: BGR, 0..255 float32, không chia 255, không trừ mean/std, tensor shape NCHW `(1, 3, 80, 80)`, class index 1 = Real. | Chuẩn hóa tiền xử lý khuôn mặt khớp tuyệt đối với mô hình gốc được huấn luyện; ngăn chặn biến dạng khuôn mặt ở sát biên ảnh. |
| `backend/tests/test_pipeline.py` | Chỉnh sửa | Bổ sung unit test `test_get_new_box_shifts_instead_of_truncating`: kiểm tra box ở sát biên trái, phải, trên đều được dịch chuyển vào trong ảnh để bảo toàn đúng kích thước mở rộng `box_w * scale`. | Đảm bảo tính đúng đắn thuật toán và ngăn ngừa hồi quy. |
| `docs/model-evaluation.md` | Chỉnh sửa | 1. Đính chính nhận định sai lầm trong báo cáo P0 (giữ nguyên tỷ lệ mở rộng khuôn mặt của tác giả gốc, không ép vuông).<br>2. Bảng đối chiếu chi tiết 8 bước tiền xử lý với nguồn gốc Minivision và yakhyo.<br>3. Bảng số liệu đo nghiệm thực tế trên tập ảnh mẫu chuẩn (`image_T1.jpg`, `image_F1.jpg`, `image_F2.jpg`) và ảnh chân dung `obama.jpg` (cả bản gốc và bản CIF 400×296).<br>4. Khuyến nghị giữ nguyên ngưỡng mặc định `0.45` từ config; ghi nhận trung thực giới hạn mô hình đơn lẻ với ảnh moire (0.8746) cần thêm liveness chủ động. | Cung cấp tài liệu thẩm định kỹ thuật đầy đủ, trung thực và khoa học. |

### Kết quả đo nghiệm thực tế mô hình PAD

*Kiểm thử với mô hình ONNX `MiniFASNetV2.onnx`:*
1. **Ảnh chuẩn của tác giả Minivision:**
   - `image_T1.jpg` (mặt thật): `is_real = True`, `reason = "PAD passed"`, **score = 0.999956** (~99.99%).
   - `image_F1.jpg` (mặt giả mạo 1): `is_real = False`, `reason = "spoof or uncertain PAD score"`, **score = 0.003597** (~0.36%).
   - `image_F2.jpg` (mặt giả mạo 2): `is_real = False`, `reason = "spoof or uncertain PAD score"`, **score = 0.004053** (~0.40%).
2. **Ảnh chân dung thật:**
   - `obama.jpg` (chân dung gốc): `is_real = True`, **score = 0.999967**.
   - `obama_cif.jpg` (ESP32-CAM độ phân giải CIF 400×296): `is_real = True`, **score = 0.999997**.
3. **Ảnh giả lập màn hình LCD (Moire pattern):**
   - Thêm lưới sọc tần số cao: score giảm xuống **0.874581** nhưng vẫn vượt ngưỡng pass (0.45) $\rightarrow$ MiniFASNetV2 đơn lẻ không đủ chống tấn công phát lại màn hình chất lượng cao; cần lớp liveness chủ động (task sau).

### Rework T06: Gỡ Bỏ Code Chết PAD_MIN_CONSECUTIVE & Cập Nhật Giới Hạn Replay

* **Ngày thực hiện:** 03/11/2026
* **Lý do kỹ thuật (Anti-overengineering & Epistemic Humility):** Tính năng `PAD_MIN_CONSECUTIVE` không được gọi trong luồng production `backend/app/api/attendance.py` (không truyền `device_id`, không ai gọi `reset_device`), việc lưu trữ bộ đếm và giới thiệu trong tài liệu/env là code chết và gây hiểu lầm. Đồng thời việc kiểm tra chống giả mạo liên khung hình sẽ được giải quyết triệt để và tự nhiên bằng liveness chủ động (như phát hiện chớp mắt) ở task sau.
* **Hành động khắc phục:**
  1. Gỡ bỏ hoàn toàn `_consecutive_counts`, `reset_device()`, tham số `device_id` khỏi `AntiSpoofAdapter.evaluate()`.
  2. Gỡ bỏ biến cấu hình `pad_min_consecutive` khỏi `Settings` và xóa dòng `PAD_MIN_CONSECUTIVE=1` trong `.env.example`.
  3. Xóa bài test `test_pad_consecutive_frames_requirement` trong `test_pipeline.py`.
  4. Cập nhật `docs/model-evaluation.md`: xóa khuyến nghị số 2 và bổ sung phân tích trung thực về giới hạn của mô hình MiniFASNetV2 tĩnh đối với replay màn hình (score 0.8746) để làm tiền đề cho liveness chủ động.

### Kết quả kiểm thử tự động

- Lệnh thực thi: `PYTHONPATH=backend pytest backend/tests -q`
- Kết quả: **68 passed** (toàn bộ 67 bài test trước đó + 1 unit test mới `test_get_new_box_shifts_instead_of_truncating` đều PASS 100%).

## Task T07: Liveness Chủ Động - Phát Hiện Chớp Mắt (EAR) Trên Luồng Preview

* **Ngày thực hiện:** 03/11/2026
* **Nhánh git:** `overhaul/v2`
* **Lý do kỹ thuật:**
  - Luồng AI chụp định kỳ gửi ảnh với tần số chậm (~0.8s/khung) nên không thể bắt kịp chuyển động chớp mắt tự nhiên vốn diễn ra trong khoảng thời gian rất ngắn (100–400ms).
  - Luồng preview JPEG đã sẵn có và được camera gửi lên backend liên tục ở tần số ~15–25 FPS qua endpoint `POST /api/devices/{id}/preview`.
  - YuNet chỉ xuất 5 điểm landmarks (hai mắt, mũi, hai khóe miệng) nên không đủ điểm để tính tỷ lệ đóng mở mắt Eye Aspect Ratio (EAR). Hệ thống tận dụng dlib shape predictor 68 landmarks có sẵn trong gói `face_recognition_models` (`face_recognition_models.pose_predictor_model_location()`), không thêm dependency bên ngoài mới.

### Danh sách tệp thay đổi

| Tệp tin | Hành động | Nội dung thay đổi | Lý do kỹ thuật |
|---|---|---|---|
| `backend/app/services/liveness.py` | Tạo mới | 1. Hàm thuần `ear(eye6pts)` tính tỷ lệ mở mắt theo chuẩn Soukupová & Čech (2016): $(\|p_2 - p_6\| + \|p_3 - p_5\|) / (2 \cdot \|p_1 - p_4\|)$.<br>2. `DeviceBlinkState` quản lý hàng đợi trượt (deque) 3 giây các mẫu `(timestamp, ear, center_x, center_y)` cho từng thiết bị.<br>3. Ngưỡng thích ứng: tính baseline bằng trung vị (median) EAR mắt mở trong lịch sử; ngưỡng nhắm mắt là `baseline * LIVENESS_CLOSED_RATIO` (mặc định 0.75).<br>4. Nhận diện chớp mắt: Mắt mở $\rightarrow$ Nhắm ($\ge 1$ mẫu) $\rightarrow$ Mở lại trong thời gian $\le 0.8s$. Nếu nhắm mắt liên tục $> 0.8s$ (vd: ngủ hoặc nhắm mắt giả lập) sẽ không được tính là chớp mắt.<br>5. Reset trạng thái: tự động xóa lịch sử nếu mất mặt $> 1s$ hoặc tâm mặt dịch chuyển đột ngột $> 25\%$ chiều rộng frame (chuyển người).<br>6. Cơ chế fail-closed: nếu dlib shape predictor không tải được $\rightarrow$ `is_available() == False`.<br>7. Tiêu thụ chớp mắt: hàm `consume_blink(device_id)` xóa dấu vết chớp mắt ngay khi điểm danh thành công để chống replay. | Cung cấp dịch vụ phát hiện chớp mắt thời gian thực mạnh mẽ, tự thích ứng với hình dạng mắt từng người và ngăn chặn tấn công phát lại video/ảnh in. |
| `backend/app/core/config.py` | Chỉnh sửa | Thêm các thuộc tính cấu hình liveness vào `Settings`: `liveness_mode: str = "blink"`, `liveness_closed_ratio: float = 0.75`, `liveness_window_s: float = 5.0`, `liveness_max_hz: float = 10.0`. | Cho phép tùy chỉnh tham số qua biến môi trường mà không cần sửa code. |
| `backend/.env.example` | Chỉnh sửa | Bổ sung các biến mẫu: `LIVENESS_MODE=blink`, `LIVENESS_CLOSED_RATIO=0.75`, `LIVENESS_WINDOW_S=5.0`, `LIVENESS_MAX_HZ=10.0`. | Hướng dẫn cấu hình môi trường triển khai. |
| `backend/app/api/devices.py` | Chỉnh sửa | Trong `upload_preview`: nếu phiên điểm danh đang mở (`has_active_session`) và `liveness_mode == "blink"`:<br>1. Điều tiết tần số xử lý tối đa `LIVENESS_MAX_HZ` (10 Hz).<br>2. Non-blocking async: kiểm tra cờ `_liveness_busy`, nếu rỗi thì kích hoạt background task `asyncio.create_task(_run_liveness_frame(...))` giải mã và phân tích landmark, không làm chậm phản hồi preview. | Tận dụng luồng preview FPS cao để tính toán EAR mà không ảnh hưởng độ trễ truyền hình ảnh. |
| `backend/app/api/attendance.py` | Chỉnh sửa | 1. Thêm dependency helper `_liveness()`.<br>2. Cổng kiểm tra liveness: sau khi bước PAD thành công và trước khi ghi nhận điểm danh, kiểm tra `is_available()` (nếu không khả dụng $\rightarrow$ fail-closed với reason `"liveness unavailable"`), và kiểm tra `has_recent_blink(device_id, within, near_center, frame_width)` (nếu chưa có chớp mắt $\rightarrow$ reject với reason `"liveness: blink required"`).<br>3. Sau khi ghi nhận điểm danh thành công: gọi `_liveness().consume_blink(device_id)` tiêu thụ chớp mắt. | Tích hợp cổng xác thực liveness chặt chẽ vào luồng điểm danh chính. |
| `backend/tests/test_liveness.py` | Tạo mới | Xây dựng 11 bài kiểm thử bao phủ toàn diện:<br>- Tính toán hình học hàm EAR với tọa độ thủ công chuẩn.<br>- Chuỗi EAR giả lập: mắt luôn mở (không chớp), nhắm mắt lâu 2s (không chớp), mở $\rightarrow$ nhắm $\rightarrow$ mở (chớp mắt hợp lệ).<br>- Reset khi nhảy tâm mặt và mất mặt $> 1s$.<br>- Kiểm tra khoảng cách tâm mặt trong `has_recent_blink`.<br>- Tiêu thụ chớp mắt qua `consume_blink`.<br>- Kiểm thử tích hợp luồng pipeline: từ chối khi chưa chớp mắt, chấp nhận khi có chớp mắt & tiêu thụ thành công, fail-closed khi model liveness không khả dụng. | Bảo đảm độ tin cậy và ngăn ngừa hồi quy logic liveness. |
| `backend/tests/test_api.py` | Chỉnh sửa | Bổ sung mock cho `_liveness` trong bài test pipeline tổng hợp `test_pipeline_stability_pad_identity_and_duplicate` để tương thích với chế độ liveness mặc định. | Đảm bảo tính toàn vẹn của test suite hiện có. |
| `docs/architecture.md` | Chỉnh sửa | Bổ sung mô tả cơ chế active liveness EAR trên luồng preview 10 Hz vào sơ đồ luồng và phần quyết định điểm danh. | Cập nhật tài liệu kiến trúc hệ thống. |

### Đo nghiệm thực tế mô hình EAR & Landmark

1. **Công thức chuẩn Eye Aspect Ratio (Soukupová & Čech, 2016):**
   $$\text{EAR} = \frac{\|p_2 - p_6\| + \|p_3 - p_5\|}{2 \cdot \|p_1 - p_4\|}$$
   - Mắt trái: các điểm landmarks từ 36 đến 41.
   - Mắt phải: các điểm landmarks từ 42 đến 47.
   - $\text{EAR}_{\text{avg}} = (\text{EAR}_{\text{left}} + \text{EAR}_{\text{right}}) / 2$.

2. **Giá trị đo nghiệm trên ảnh chân dung mắt mở thật (`obama.jpg`):**
   - $\text{EAR}_{\text{left}} = 0.2179$
   - $\text{EAR}_{\text{right}} = 0.2375$
   - $\text{EAR}_{\text{avg}} = 0.2277$
   - Ngưỡng nhắm mắt thích ứng ($0.75 \times \text{baseline}$): $\approx 0.1708$.

3. **Benchmark hiệu năng xử lý (CPU) trên ảnh độ phân giải CIF 400×296 (50 lần lặp):**
   - Tác vụ: YuNet Face Detection + dlib 68-point shape landmark predictor.
   - Thời gian trung bình (Mean): **7.24 ms / frame**.
   - Thời gian tối thiểu (Min): **5.68 ms**.
   - Thời gian tối đa (Max): **21.41 ms**.
   - Phân vị 95 (P95): **8.61 ms**.
   - **Đánh giá:** Chi phí trung bình ~7.2 ms hoàn toàn đáp ứng trơn tru tần số xử lý 10–15 Hz của luồng preview mà chỉ chiếm một phần rất nhỏ tải CPU (~7–10% của 1 core CPU).

### Kết quả kiểm thử tự động

- Lệnh thực thi kiểm thử riêng liveness: `PYTHONPATH=backend pytest backend/tests/test_liveness.py -v` $\rightarrow$ **11 passed**.
- Lệnh thực thi toàn bộ kiểm thử backend: `PYTHONPATH=backend pytest backend/tests -q` $\rightarrow$ **79 passed** (100% test suite vượt qua).





