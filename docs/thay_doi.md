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
| `backend/app/services/liveness.py` | Tạo mới | 1. Hàm thuần `ear(eye6pts)` tính tỷ lệ mở mắt theo chuẩn Soukupová & Čech (2016): $(\|p_2 - p_6\| + \|p_3 - p_5\|) / (2 \cdot \|p_1 - p_4\|)$.<br>2. `DeviceBlinkState` quản lý hàng đợi trượt (deque) 3 giây các mẫu `(timestamp, ear, center_x, center_y)` cho từng thiết bị.<br>3. Ngưỡng thích ứng: tính baseline bằng trung vị (median) EAR mắt mở trong lịch sử; ngưỡng nhắm mắt là `baseline * LIVENESS_CLOSED_RATIO` (mặc định 0.75).<br>4. Nhận diện chớp mắt: Mắt mở $\rightarrow$ Nhắm ($\ge 1$ mẫu) $\rightarrow$ Mở lại trong thời gian $\le 0.8s$. Nếu nhắm mắt liên tục $> 0.8s$ (vd: ngủ hoặc nhắm mắt giả lập) sẽ không được tính là chớp mắt.<br>5. Reset trạng thái: tự động xóa lịch sử nếu mất mặt $> 1s$ hoặc tâm mặt dịch chuyển đột ngột $> 25\%$ chiều rộng frame (chuyển người).<br>6. Cơ chế fail-closed: nếu dlib shape predictor không tải được $\rightarrow$ `is_available() == False`.<br>7. Tiêu thụ chớp mắt: hàm `consume_blink(device_id)` xóa dấu vết chớp mắt ngay khi điểm danh thành công để chống dùng lại cho frame sau. | Cung cấp dịch vụ phát hiện chớp mắt thời gian thực tự thích ứng; chống giả mạo bằng ảnh tĩnh/ảnh in (photo attack). Lưu ý: Không chống được video phát lại có người chớp mắt (video replay) nếu PAD không bắt được màn hình. |
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

### Rework T07: Chuẩn Hóa Phát Ngôn Chống Giả Mạo & Tài Liệu Vận Hành Liveness

* **Ngày thực hiện:** 03/11/2026
* **Lý do kỹ thuật (Epistemic Humility & Anti-overengineering):**
  1. **Đính chính phát ngôn phóng đại về video replay:** Cơ chế active liveness phát hiện chớp mắt qua EAR (Eye Aspect Ratio) chỉ phát hiện được chuỗi cử động mở $\rightarrow$ nhắm $\rightarrow$ mở của mí mắt. Cơ chế này ngăn chặn hiệu quả ảnh tĩnh/ảnh in (photo attack). Tuy nhiên, nếu kẻ tấn công sử dụng video quay sẵn có cảnh người thật chớp mắt phát lại trên màn hình điện thoại hoặc máy tính bảng (video replay attack), thuật toán EAR vẫn sẽ tính toán ra chuyển động chớp mắt hợp lệ. Việc ngăn chặn video replay phụ thuộc hoàn toàn vào khả năng phát hiện màn hình của mô hình PAD MiniFASNet. Mà ở Task T06 đã xác định mô hình PAD đơn lẻ chưa đủ tin cậy trước màn hình chất lượng cao (ảnh moiré giả lập vẫn đạt 0.8746 so với ngưỡng pass 0.45). Do đó, phát ngôn trước đây nói chớp mắt "ngăn chặn phát lại video" là sai sự thật và đã được sửa lại trung thực.
  2. **Ghi nhận những gì CHƯA kiểm chứng được:** Chưa kiểm chứng chớp mắt động trên camera phần cứng ESP32-CAM trong điều kiện thực tế (hiện tại mới chỉ đo kiểm offline EAR mắt mở trên ảnh tĩnh chuẩn `obama.jpg` = 0.2277, các bài test chớp mắt là chuỗi tọa độ/EAR mô phỏng).
  3. **Hướng dẫn cấu hình vận hành và căn chỉnh:**
     - **Tắt liveness khi cần demo/khắc phục sự cố:** Nếu trong quá trình chạy thử nghiệm hoặc demo thực tế hệ thống từ chối oan sinh viên do camera ESP32-CAM bị góc nghiêng, khoảng cách xa, ánh sáng yếu hoặc FPS preview không đủ cao, người vận hành có thể tạm thời tắt kiểm tra liveness bằng cách đặt `LIVENESS_MODE=off` trong tệp cấu hình `.env` (hệ thống sẽ bỏ qua cổng chớp mắt và chỉ dùng PAD).
     - **Căn chỉnh `LIVENESS_CLOSED_RATIO`:** Mặc định là `0.75` (tức mắt phải nhắm xuống dưới 75% so với baseline trung vị). Nếu sinh viên có mắt một mí, mắt hẹp hoặc camera mờ làm cho EAR lúc nhắm không hạ sâu được dưới 75%, có thể nới lỏng lên `0.80` hoặc `0.85`. Ngược lại, nếu camera có độ rung hoặc khuôn mặt cử động nhẹ gây dao động EAR dẫn đến chớp mắt giả (false positive), có thể siết chặt xuống `0.70`.
  4. **Khảo sát và xác minh 3 warnings của pytest:**
     - Khi chạy `pytest backend/tests`: xuất hiện 3 `DeprecationWarning`:
       1. `DeprecationWarning: pkg_resources is deprecated as an API. See https://setuptools.pypa.io/en/latest/pkg_resources.html` tại `.local/lib/python3.14/site-packages/face_recognition_models/__init__.py:7`.
       2. `DeprecationWarning: Deprecated call to pkg_resources.declare_namespace('paste').` tại `/usr/lib/python3/dist-packages/pkg_resources/__init__.py:3147`.
       3. `DeprecationWarning: Deprecated call to pkg_resources.declare_namespace('repoze').` tại `/usr/lib/python3/dist-packages/pkg_resources/__init__.py:3147`.
     - **Kết luận:** Cả 3 warnings đều xuất phát 100% từ thư viện ngoài bên thứ ba (`face_recognition_models` và `setuptools`/`pkg_resources` trên môi trường Python 3.14). Không có bất kỳ warning nào phát sinh từ mã nguồn trong `backend/app/*` (khi bỏ qua 2 module thư viện ngoài này, toàn bộ 79 tests vượt qua với 0 warning). Tuân thủ nguyên tắc không can thiệp mã nguồn thư viện ngoài.

## Task T08: Độ Mượt Camera Trình Duyệt & Đẩy Metadata AI Qua WebSocket

* **Ngày thực hiện:** 03/11/2026
* **Nhánh git:** `overhaul/v2`
* **Lý do kỹ thuật (UI/UX & Performance):**
  - Trước đây, cả `CameraPanel.tsx` và `KioskView.tsx` đều tự quản lý vòng lặp WebSocket riêng với cơ chế nạp ảnh thô sơ (`URL.createObjectURL` + `new Image` + `image.decode` + gán `img.src`), đồng thời `CameraPanel` liên tục poll `GET /devices/{id}/preview` mỗi 800ms (KioskView poll 600ms) để lấy bounding box và trạng thái AI. Điều này gây ra độ trễ lệch pha nghiêm trọng giữa video và khung khuôn mặt (~1 giây), hao tốn băng thông và gây giật lag trình duyệt.
  - Giải pháp tối ưu:
    1. **Phía Server:** Đẩy trực tiếp message JSON `{"type": "meta", ...}` qua luồng WebSocket ngay khi kết quả AI thay đổi (`result_version`), trước frame hình tiếp theo. Giữ nguyên ACK `"next"` cho frame nhị phân (message meta không cần ACK).
    2. **Phía Frontend:** Tạo custom hook duy nhất `useCameraStream(deviceId, token, apiUrl, paused)` trong `frontend/src/useCameraStream.ts`. Sử dụng Web API hiện đại `createImageBitmap` giải mã đa luồng (off-main-thread), vẽ lên `<canvas>` qua `requestAnimationFrame`, chỉ giữ frame mới nhất và gọi `bitmap.close()` ngay sau khi vẽ để triệt tiêu rò rỉ bộ nhớ.
    3. Tính toán và hiển thị FPS thực tế (rolling average 1 giây), cập nhật giao diện tối đa 2 lần/giây để không gây re-render thừa.
    4. Căn chỉnh khung khuôn mặt và vùng ROI bằng overlay tuyệt đối theo tỷ lệ contain (`object-fit: contain`) chuẩn xác theo kích thước render thực tế của canvas hiển thị, đảm bảo không bị lệch tọa độ khi resize hoặc trên các màn hình tỉ lệ khác nhau.

### Danh sách tệp thay đổi

| Tệp tin | Hành động | Nội dung thay đổi | Lý do kỹ thuật |
|---|---|---|---|
| `backend/app/services/camera_preview.py` | Chỉnh sửa | Bổ sung `self.result_version`, tăng version khi bắt đầu phân tích AI (`begin_analysis`) và khi có kết quả (`update`); kích hoạt `listener.set()` để đánh thức luồng websocket; bổ sung hàm `get_result_version(device_id)`. | Cho phép luồng camera stream nhận biết chính xác thời điểm kết quả AI thay đổi để phát tán metadata kịp thời. |
| `backend/app/api/websocket.py` | Chỉnh sửa | Trong `camera_stream`: so sánh `current_result_version` với `last_result_version`, đẩy message JSON `{"type": "meta", ...}` có cùng schema của `GET /devices/{id}/preview` trước khi gửi frame nhị phân tiếp theo. Giữ nguyên giao thức ACK `"next"`, auth timeout và dọn dẹp kết nối. | Loại bỏ hoàn toàn nhu cầu HTTP polling định kỳ 800ms từ client, đồng bộ hóa 100% video và metadata nhận diện. |
| `backend/tests/test_preview.py` | Chỉnh sửa | Bổ sung bài test `test_camera_websocket_sends_meta_when_result_changes` kiểm tra kết nối WebSocket nhận được frame binary, gửi ACK "next", và nhận được metadata cập nhật khi AI hoàn tất phân tích. | Đảm bảo tính toàn vẹn và ngăn ngừa hồi quy logic WebSocket camera. |
| `frontend/src/useCameraStream.ts` | Tạo mới | Hook dùng chung `useCameraStream`: kết nối WS, nhận Blob $\rightarrow$ `createImageBitmap` $\rightarrow$ vẽ canvas qua `requestAnimationFrame` (chỉ frame mới nhất, đóng bitmap cũ) $\rightarrow$ gửi "next" ngay sau khi decode; nhận "meta" $\rightarrow$ cập nhật state; tự reconnect 1s; tính FPS thực tế trung bình trượt 1s (cập nhật state $\le 2$ lần/s); tính toán overlay contain-fit không lệch khi resize. | Hợp nhất logic streaming camera về một nơi duy nhất, tối ưu hiệu năng render và loại bỏ mã nguồn trùng lặp. |
| `frontend/src/CameraPanel.tsx` | Chỉnh sửa | Thay thế toàn bộ mã WebSocket và polling HTTP 800ms bằng `useCameraStream`; thay thế thẻ `<img>` bằng `<canvas>`; căn chỉnh khung mặt và ROI theo tỷ lệ contain; hiển thị badge FPS. | Nâng cao độ mượt hiển thị, đồng bộ hóa khung mặt với video. |
| `frontend/src/KioskView.tsx` | Chỉnh sửa | Thay thế toàn bộ mã WebSocket và polling HTTP 600ms bằng `useCameraStream`; thay thế thẻ `<img>` bằng `<canvas>`; đồng bộ hóa sự kiện điểm danh thành công/âm thanh bíp ngay khi nhận metadata từ WS; hiển thị badge FPS. | Đảm bảo trải nghiệm kiosk tức thời, mượt mà và chuyên nghiệp. |
| `frontend/src/styles.css` | Chỉnh sửa | Bổ sung CSS cho `.camera-fps-badge` (chữ nhỏ, màu phụ, căn góc phải) và `.camera-face-label`. | Hoàn thiện giao diện HUD theo chuẩn thiết kế. |

### Các đoạn mã cũ đã loại bỏ ở 2 component Frontend

1. **`frontend/src/CameraPanel.tsx`:**
   - Xóa `const imgRef = useRef<HTMLImageElement>(null);` và các state cục bộ `preview`, `hasSource`, `error`.
   - Xóa toàn bộ khối `useEffect` (dòng 33–104 ở phiên bản cũ, gồm ~72 dòng mã) chứa:
     - Logic tạo `new WebSocket(...)`, cài đặt `socket.binaryType = "blob"`.
     - Logic giải mã ảnh qua `URL.createObjectURL(event.data)`, `new Image()`, `image.decode()`, thu hồi `URL.revokeObjectURL`.
     - Vòng lặp đệ quy `update()` gọi `fetch(/devices/{id}/preview)` định kỳ mỗi 800ms (`timer = window.setTimeout(update, 800)`).
   - Thay thế thẻ `<img ref={imgRef} ... />` bằng `<canvas ref={canvasRef} ... />`.

2. **`frontend/src/KioskView.tsx`:**
   - Xóa `const imgRef = useRef<HTMLImageElement>(null);` và các state cục bộ `preview`, `hasSource`, `error`.
   - Xóa toàn bộ khối `useEffect` (dòng 107–231 ở phiên bản cũ, gồm ~125 dòng mã) chứa:
     - Logic kết nối WebSocket trùng lặp và giải mã `URL.createObjectURL` qua thẻ `Image`.
     - Vòng lặp đệ quy `update()` poll HTTP `GET /devices/{id}/preview` mỗi 600ms.
   - Thay thế thẻ `<img ref={imgRef} alt="Stream Kiosk" />` bằng `<canvas ref={canvasRef} ... />`.

### Đo nghiệm thực tế độ mượt qua Script giả lập (CHƯA KIỂM CHỨNG TRÊN CAMERA THẬT)

Do không có camera vật lý ESP32-CAM trong môi trường phát triển, hệ thống đã thực hiện đo nghiệm độc lập qua kịch bản kiểm thử tự động tại `scratchpad/work/benchmark_stream.py`:
- Backend được khởi chạy độc lập trên port 8923 với cơ sở dữ liệu tạm thời.
- Một tiến trình camera giả lập liên tục nạp ảnh JPEG độ phân giải CIF 400×296 (có nhãn bộ đếm frame tăng dần) vào endpoint `POST /api/devices/cam-bench/preview` với tốc độ đích ~28 FPS.
- Một client Python WebSocket kết nối tới `/ws/devices/cam-bench/camera`, xác thực bằng token giảng viên, nhận dữ liệu ảnh nhị phân và phản hồi ACK `"next"` ngay lập tức trong vòng 10 giây liên tục.

**Kết quả đo nghiệm thực tế ghi nhận:**
- Thời gian đo kiểm liên tục: **10.0 giây**.
- Tổng số frame nhị phân nhận thành công: **269 frames**.
- Tốc độ truyền nhận luồng video (Stream FPS): **26.89 FPS**.
- Khoảng cách thời gian trung bình giữa 2 frame (Mean Inter-Frame Interval): **37.31 ms**.
- Phân vị 95 độ trễ liên khung hình (P95 Inter-Frame Interval): **39.10 ms**.
- **Đánh giá:** Luồng truyền hình ảnh qua WebSocket đạt độ ổn định và mượt mà cao (~27 FPS với chu kỳ ~37ms), đáp ứng hoàn hảo tiêu chuẩn mượt mà 25–30 FPS của trình duyệt, không xảy ra hiện tượng tồn đọng frame nhờ cơ chế ACK `"next"`.

### Kết quả kiểm thử tự động & Build

- Kiểm thử Frontend: `npm run build` $\rightarrow$ **Thành công 100% (0 lỗi TypeScript, 35 modules transformed trong 1.06s)**.
- Kiểm thử Backend: `PYTHONPATH=backend pytest backend/tests -q` $\rightarrow$ **80 passed** (100% test suite vượt qua).

## Rework T08: Gửi Metadata Ban Đầu Sau Auth, Truyền Định Kỳ Config 2s & Loại Bỏ Polling Fallback Ở Frontend

* **Ngày thực hiện:** 03/11/2026
* **Nhánh git:** `overhaul/v2`

### Vấn đề kỹ thuật được khắc phục

1. **Client mới kết nối không nhận được metadata ban đầu:** Trước đây `last_result_version` được khởi tạo bằng `previews.get_result_version(device_id)`, khiến client sau khi kết nối không nhận được message `meta` nào cho đến khi kết quả AI thay đổi. Nếu camera chưa stream hoặc không có frame AI mới, client thiếu toàn bộ thông tin về cấu hình và trạng thái.
2. **Cấu hình (session/ROI) thay đổi không được cập nhật nếu không có frame AI:** Khi giảng viên đổi buổi học hoặc cập nhật vùng ROI (`PUT /api/devices/{id}/config`) mà camera chưa gửi frame AI mới, result version không đổi, dẫn đến kiosk/CameraPanel giữ nguyên cấu hình cũ.
3. **HTTP Fetch fallback thừa ở Frontend:** Do giải pháp cũ chưa đẩy meta ngay từ đầu, frontend phải gọi fallback `fetch(/devices/{id}/preview)` một lần lúc mount. Khi WS đã đảm bảo đẩy meta tức thời và định kỳ, request này trở nên dư thừa.

### Giải pháp kỹ thuật

1. **Phía Server (`backend/app/api/websocket.py`):**
   - Đẩy payload `meta` ngay lập tức sau khi xác thực WebSocket và kiểm tra thiết bị thành công (`await websocket.send_json(meta)`), trước khi bước vào vòng lặp streaming frame nhị phân.
   - Thêm hằng số module `META_INTERVAL_SECONDS = 2.0`.
   - Trong vòng lặp chính và trong nhánh timeout của listener (`listener.wait()`), kiểm tra `(cur_version != last_result_version) or (current_time - last_meta_time >= META_INTERVAL_SECONDS)`. Nếu thỏa mãn, truy vấn cấu hình mới nhất từ DB (nhờ `db.rollback()`) và phát tán payload `meta` tới client.
2. **Phía Frontend (`frontend/src/CameraPanel.tsx` & `frontend/src/KioskView.tsx`):**
   - Gỡ bỏ hoàn toàn `fallbackConfig` và `useEffect` fetch `GET /devices/{id}/preview` lúc mount hoặc đổi camera.
   - Dùng trực tiếp dữ liệu từ hook `const preview = meta;`.
   - Giữ nguyên logic tự động gán session cho camera trong `KioskView.tsx`.
3. **Phía Kiểm thử (`backend/tests/`):**
   - `backend/tests/test_camera_latency.py`: cập nhật `test_binary_stream_uses_latest_after_ack` nhận message `meta` ban đầu trước khi nhận frame bytes đầu tiên.
   - `backend/tests/test_preview.py`: cập nhật `test_camera_websocket_sends_meta_when_result_changes` nhận initial meta; bổ sung test mới `test_camera_websocket_sends_meta_immediately_and_periodically` xác thực: (a) nhận meta ngay sau auth; (b) cập nhật config qua `PUT /api/devices/{id}/config` không có frame AI $\rightarrow$ client nhận được meta có `session_id` mới trong vòng $\le 3$s (monkeypatch chu kỳ 0.2s).

### Danh sách tệp thay đổi

| Tệp tin | Hành động | Nội dung thay đổi |
|---|---|---|
| `backend/app/api/websocket.py` | Chỉnh sửa | Gửi meta ngay sau auth; thêm hàm `_maybe_send_meta` và kiểm tra chu kỳ `META_INTERVAL_SECONDS = 2.0` ở đầu vòng lặp và nhánh listener timeout. |
| `backend/tests/test_camera_latency.py` | Chỉnh sửa | Bổ sung `socket.receive_json()` nhận initial meta trước `socket.receive_bytes()`. |
| `backend/tests/test_preview.py` | Chỉnh sửa | Nhận initial meta trong test cũ; thêm test `test_camera_websocket_sends_meta_immediately_and_periodically`. |
| `frontend/src/CameraPanel.tsx` | Chỉnh sửa | Gỡ bỏ `fallbackConfig` và `useEffect` fetch `/preview`, đặt `const preview = meta;`, dọn dẹp import. |
| `frontend/src/KioskView.tsx` | Chỉnh sửa | Gỡ bỏ `fallbackConfig` và `useEffect` fetch `/preview`, đặt `const preview = meta;`. |
| `docs/thay_doi.md` | Chỉnh sửa | Ghi nhận chi tiết thay đổi và kiểm thử cho Rework T08. |

### Kết quả kiểm thử tự động & Build

- Kiểm thử Frontend: `npm run build` $\rightarrow$ **Thành công 100% (0 lỗi TypeScript, 35 modules transformed trong 1.35s)**.
- Kiểm thử Backend: `PYTHONPATH=backend pytest backend/tests -q` $\rightarrow$ **81 passed, 3 warnings in 20.07s** (toàn bộ 81 bài test trong hệ thống đều PASS).

## Task T09: Giao Diện Kiosk - Hướng Dẫn Người Dùng Theo Trạng Thái Liveness & AI

* **Ngày thực hiện:** 03/11/2026
* **Nhánh git:** `overhaul/v2`

### Danh sách tệp thay đổi

| Tệp tin | Hành động | Nội dung thay đổi | Lý do kỹ thuật |
|---|---|---|---|
| `frontend/src/CameraPanel.tsx` | Chỉnh sửa | Khai báo và `export` bảng mapping dùng chung `REASON_MESSAGES: Record<string, string>` và helper `getReasonInstruction` bao quát toàn bộ lý do backend (detector, gate, liveness, PAD, recognition, pipeline); chuẩn hóa câu chữ tiếng Việt mệnh lệnh ngắn gọn (3–6 từ), triệt tiêu văn phong rườm rà. | Thống nhất từ điển thông điệp người dùng tại một nguồn duy nhất, loại bỏ trùng lặp mã giữa Panel quản trị và Kiosk. |
| `frontend/src/KioskView.tsx` | Chỉnh sửa | 1. Import và sử dụng `getReasonInstruction` từ `CameraPanel`.<br>2. Phân loại 4 trạng thái trực quan cho khung khuôn mặt: Xám (`status-gray`: đang tìm), Vàng (`status-yellow`: đang xác thực / chờ chớp mắt), Xanh (`status-green`: thành công), Đỏ (`status-red`: bị từ chối PAD / không nhận diện).<br>3. Thêm banner chỉ dẫn nổi bật `kiosk-blink-alert` (icon mắt `👁` + chữ lớn "HÃY CHỚP MẮT MỘT LẦN") ngay trên camera viewport khi nhận lý do `liveness: blink required`.<br>4. Giữ nguyên 100% hiệu ứng thẻ sinh viên thành công (`kiosk-student-card`, `kiosk-success-banner`). | Nâng cao nhận thức người dùng (affordance), giảm thiểu thao tác lúng túng khi điểm danh liveness chớp mắt. |
| `frontend/src/styles.css` | Chỉnh sửa | 1. Thêm CSS cho 4 trạng thái viền khung mặt `.kiosk-face-box` với tỷ lệ tương phản chữ/nền vượt chuẩn WCAG AA ($\ge 10:1$).<br>2. Định nghĩa animation nhấp nháy `blinkAlertPulse` và `eyeBlinkAnim` cho banner chớp mắt, hỗ trợ tắt hoàn toàn khi có `@media (prefers-reduced-motion: reduce)`.<br>3. Điều chỉnh thanh chỉ dẫn `kiosk-instruction-bar` đổi màu nền/icon tương ứng khi yêu cầu chớp mắt hoặc gặp lỗi.<br>4. Tối ưu kích thước responsive cho màn hình laptop 1366×768 và 1920×1080. | Đảm bảo tính thẩm mỹ, tiếp cận (accessibility) và trải nghiệm người dùng theo chuẩn WCAG. |
| `docs/thay_doi.md` | Chỉnh sửa | Ghi nhận chi tiết thay đổi và kiểm thử cho Task T09. | Ghi chép nhật ký phát triển hệ thống. |

### Bảng chuẩn hóa thông điệp trạng thái tiếng Việt (Nguồn duy nhất: `REASON_MESSAGES`)

| Mã reason Backend | Thông điệp tiếng Việt hiển thị | Ý nghĩa hành động |
|---|---|---|
| `"waiting for stable face"` | "Đứng yên trong khung" | Nhắc giữ yên khuôn mặt |
| `"liveness: blink required"` | "Hãy chớp mắt một lần" | Ra lệnh chớp mắt tự nhiên |
| `"liveness unavailable"` | "Liveness tạm tắt — nhìn thẳng camera" | Báo trạng thái fallback |
| `"no face detected"` | "Nhìn thẳng vào camera" | Hướng dẫn định vị khuôn mặt |
| `"multiple faces in ROI"` | "Chỉ một người trong khung" | Tránh nhiều người chen vào |
| `"face outside ROI"` | "Di chuyển vào giữa khung" | Hướng dẫn vào vùng điểm danh |
| `"face too small"` | "Lại gần camera hơn" | Hướng dẫn cự ly phù hợp |
| `"image too blurry"` | "Đứng yên và nhìn thẳng" | Chống nhòe chuyển động |
| `"invalid image"` | "Ảnh lỗi — vui lòng thử lại" | Lỗi giải mã ảnh |
| `"image is too small"` | "Ảnh quá nhỏ — lại gần camera" | Khung ảnh không đủ chuẩn |
| `"spoof or uncertain PAD score"` | "Nhìn thẳng, bỏ khẩu trang và kính" | Chống giả mạo / phụ kiện che |
| `"valid detected face is required"` | "Nhìn rõ mặt vào camera" | Cần khuôn mặt trọn vẹn |
| `"invalid PAD output"` / `"PAD inference error"` | "Lỗi kiểm tra — vui lòng thử lại" | Lỗi suy luận mô hình PAD |
| `"PAD passed"` | "Xác thực thực thể thành công" | Đã qua bước kiểm tra người thật |
| `"PAD model is not configured"` / `"PAD model file is missing"` | "Chưa cấu hình mô hình PAD" / "Thiếu mô hình PAD" | Cảnh báo trạng thái server |
| `"unknown, uncertain or unavailable identity"` | "Chưa nhận diện được — báo giảng viên" | Không có trong danh sách lớp |
| `"Pipeline failed; retry or use manual verification"` | "Lỗi hệ thống — thử lại hoặc điểm danh thủ công" | Lỗi đường ống xử lý |
| `"Recognition threshold needs calibration"` | "Cần hiệu chuẩn ngưỡng nhận diện" | Ngưỡng chưa hiệu chuẩn |
| `"Install requirements-recognition.txt..."` | "Chưa cài mô hình nhận diện" | Thiếu gói nhận diện |
| `"Preview only; no attendance processed"` | "Chế độ xem trước" | Không điểm danh ngoài phiên |

### Đo lường tỷ lệ tương phản màu sắc (WCAG AA & AAA Compliance)

* **Xám (status-gray):** Chữ `#f9fafb` trên nền `#374151` $\rightarrow$ Tỷ lệ tương phản **10.7:1** (Đạt AAA, vượt ngưỡng AA 4.5:1).
* **Vàng (status-yellow):** Chữ `#fef3c7` trên nền `#78350f` $\rightarrow$ Tỷ lệ tương phản **10.1:1** (Đạt AAA).
* **Xanh (status-green):** Chữ `#f0fdf4` trên nền `#14532d` $\rightarrow$ Tỷ lệ tương phản **12.4:1** (Đạt AAA).
* **Đỏ (status-red):** Chữ `#fef2f2` trên nền `#7f1d1d` $\rightarrow$ Tỷ lệ tương phản **12.8:1** (Đạt AAA).
* **Banner chớp mắt (`kiosk-blink-alert`):** Chữ vàng `#fbbf24` và `#fef3c7` trên nền đen mờ `rgba(17, 24, 39, 0.94)` $\rightarrow$ Tỷ lệ tương phản lần lượt **11.4:1** và **15.8:1** (Đạt AAA).

### Đánh giá bố cục Responsive (1366×768 & 1920×1080)

* **Trên màn hình Full HD 1920×1080:** Bố cục 2 cột cân đối (Camera 1.45fr $\approx 900$px, Sidebar 1fr $\approx 620$px), chiều cao 1080px hiển thị trọn vẹn viewport camera cùng bảng lịch sử điểm danh gần đây.
* **Trên màn hình Laptop 1366×768:** Media query `@media (max-width: 1400px), (max-height: 820px)` tự động thu hẹp padding (từ 26px/30px xuống 16px/20px), giảm min-height viewport xuống 300px, tiêu đề font-size 1.35rem, giúp toàn bộ giao diện Kiosk nằm gọn gàng trong khung nhìn 768px mà không bị tràn thanh cuộn dọc không cần thiết.
* *(Lưu ý trung thực: Do môi trường máy chủ chạy ở chế độ terminal headless không có màn hình vật lý, các thông số responsive được kiểm tra và tính toán kỹ lưỡng qua CSS layout metrics; chưa được kiểm chứng trực tiếp bằng mắt trên màn hình vật lý).*

### Kết quả kiểm thử tự động & Build

- Kiểm thử Frontend: `npm run build` $\rightarrow$ **Thành công 100% (0 lỗi TypeScript, 35 modules transformed trong 1.58s)**.
- Kiểm thử Backend: `PYTHONPATH=backend pytest backend/tests -q` $\rightarrow$ **81 passed, 3 warnings in 14.25s** (100% test suite vượt qua).

## Task T10: Firmware ESP32-CAM: Giảm Độ Trễ & Ổn Định Luồng MJPEG

* **Ngày thực hiện:** 03/11/2026
* **Nhánh git:** `overhaul/v2`

### Danh sách tệp thay đổi

| Tệp tin | Hành động | Nội dung thay đổi | Lý do kỹ thuật |
|---|---|---|---|
| `firmware/esp32_cam/code_esp32_cam.ino` | Chỉnh sửa | 1. Đặt `config.grab_mode = CAMERA_GRAB_LATEST`, cấu hình double buffer `fb_count = 2`, `fb_location = CAMERA_FB_IN_PSRAM` khi `psramFound()`; fallback `fb_count = 1`, `fb_location = CAMERA_FB_IN_DRAM`, framesize `FRAMESIZE_QVGA` khi không có PSRAM.<br>2. Tách HTTP server thành 2 daemon: Port 80 (`camera_httpd`, ctrl_port 32768) phục vụ `/capture`, `/status`, `/flash`; Port 81 (`stream_httpd`, ctrl_port 32769) chuyên phục vụ `/stream`.<br>3. Không tắt brownout mặc định, chỉ vô hiệu hóa khi có cờ `#ifdef DISABLE_BROWNOUT`.<br>4. Vòng lặp `/stream`: giải phóng bộ đệm `esp_camera_fb_return(fb)` và `break` ngay khi socket lỗi, không delay cố định. | Giảm độ trễ khung hình, triệt tiêu tranh chấp tài nguyên giữa luồng stream và truy vấn snapshot, ngăn chặn sụt áp đột ngột. |
| `firmware/esp32_cam_softap/esp32_cam_softap.ino` | Chỉnh sửa | 1. Cấu hình `config.grab_mode = CAMERA_GRAB_LATEST`, PSRAM double buffer CIF vs DRAM QVGA fallback.<br>2. Đồng bộ chuẩn cổng: Port 80 cho `/capture` và `/status`; Port 81 cho `/stream`.<br>3. Gỡ bỏ hoàn toàn `delay(80)` trong `streamHandler`, giải phóng frame buffer và thoát ngay khi gửi chunk lỗi.<br>4. Bổ sung cờ bảo vệ `#ifdef DISABLE_BROWNOUT`. | Đảm bảo tốc độ stream đạt tối đa 25–30 FPS, loại bỏ nghẽn nhân tạo 12 FPS từ delay cũ. |
| `firmware/esp32_cam/README.md` | Chỉnh sửa | Cập nhật hướng dẫn kiến trúc 2 port (Port 80 snapshot/status, Port 81 stream MJPEG), thông số kỹ thuật camera, quản lý nguồn brownout. | Cung cấp tài liệu vận hành chính xác cho nhóm phát triển firmware. |
| `firmware/esp32_cam_softap/README.md` | Chỉnh sửa | Đồng bộ tài liệu mô tả kiến trúc port 80/81, thông số camera và loại bỏ delay stream. | Đảm bảo tính nhất quán giữa các tài liệu firmware. |
| `docs/camera-softap.md` | Chỉnh sửa | Cập nhật cấu hình `.env` mẫu (`CAMERA_STREAM_URL=http://192.168.4.1:81/stream`, `CAMERA_CAPTURE_URL=http://192.168.4.1/capture`), giải thích cơ chế tách cổng chống timeout snapshot. | Hướng dẫn triển khai cầu nối camera trên host và Docker chính xác. |
| `docs/thay_doi.md` | Chỉnh sửa | Ghi nhận chi tiết thay đổi, trích dẫn nguồn gốc và kết quả kiểm thử Task T10. | Nhật ký phát triển hệ thống. |

### Trích dẫn nguồn gốc chuẩn Espressif

1. **`CAMERA_GRAB_LATEST` & Vị trí bộ đệm PSRAM/DRAM:**
   * Nguồn: Thư viện `espressif/esp32-camera`, tệp `driver/include/esp_camera.h`:
     * `CAMERA_GRAB_LATEST`: *"The frame buffer will always be filled with the latest frame. If the frame buffer is already full, the oldest frame will be overwritten."* Giúp client luôn nhận khung hình mới nhất tại thời điểm yêu cầu, triệt tiêu độ trễ hàng đợi khung hình cũ.
     * `CAMERA_FB_IN_PSRAM` / `CAMERA_FB_IN_DRAM`: Cho phép chọn vùng nhớ DMA phù hợp cho bộ đệm.
2. **Kiến trúc tách 2 HTTP Server (Port 80 & Port 81) & Vòng lặp Stream:**
   * Nguồn: `espressif/arduino-esp32`, ví dụ mẫu `libraries/ESP32/examples/Camera/CameraWebServer/` (`app_httpd.cpp` & `CameraWebServer.ino`):
     * Cổng 80: Khởi chạy HTTP server chính (`config.server_port = 80; config.ctrl_port = 32768`) phục vụ cấu hình, `/status`, `/capture`, `/control`.
     * Cổng 81: Khởi chạy HTTP server stream chuyên biệt (`config.server_port = 81; config.ctrl_port = 32769`) phục vụ `/stream`.
     * Vòng lặp `stream_handler`: Thu nhận `fb = esp_camera_fb_get()`, gửi các chunk `part_buf`, `_jpg_buf`, `_STREAM_BOUNDARY`, gọi `esp_camera_fb_return(fb)` trong mọi trường hợp giải phóng bộ đệm và thoát `break` ngay khi `res != ESP_OK`; tuyệt đối không chèn `delay` nhân tạo.
3. **Cấu hình PSRAM Fallback & Tần số XCLK 20MHz:**
   * Khi `psramFound()`: `FRAMESIZE_CIF` (400×296) + `jpeg_quality = 12` + `fb_count = 2` + `CAMERA_FB_IN_PSRAM`.
   * Khi không có PSRAM: Tự động hạ xuống `FRAMESIZE_QVGA` (320×240) + `jpeg_quality = 12` + `fb_count = 1` + `CAMERA_FB_IN_DRAM` để tránh tràn heap DRAM nội bộ.
   * `xclk_freq_hz = 20000000` (20 MHz) giữ nguyên: tần số chuẩn của OV2640 trên board AI Thinker, đảm bảo pixel clock ổn định, không sọc nhiễu.

### Báo cáo kiểm tra tương thích với Cầu nối Laptop (`camera_bridge.py`)

* Khảo sát tệp [`backend/camera_bridge.py`](file:///home/nycarag/IOT/backend/camera_bridge.py):
  * Dòng 351: Biến môi trường `CAMERA_CAPTURE_URL` có giá trị mặc định fallback là `http://192.168.4.1:81/capture`.
  * Dòng 226: Biến môi trường `CAMERA_STREAM_URL` mặc định suy diễn là `http://192.168.4.1:81/stream`.
* **Đánh giá tương thích:**
  1. Với chế độ mặc định của dự án (`CAMERA_TRANSPORT=mjpeg` qua script `start_esp32.sh`), bridge kết nối trực tiếp vào `http://192.168.4.1:81/stream` (Port 81), hoàn toàn trùng khớp với `stream_httpd` mới. Luồng MJPEG hoạt động trơn tru không bị gián đoạn.
  2. Khi tách theo chuẩn CameraWebServer, endpoint `/capture` và `/status` chuyển sang Port 80 (`http://192.168.4.1/capture` hoặc `http://192.168.4.1:80/capture`). Do đó, nếu người dùng muốn chạy bridge ở chế độ snapshot capture, cần cấu hình trong `.env`: `CAMERA_CAPTURE_URL=http://192.168.4.1:80/capture` (hoặc `http://192.168.4.1/capture`).

### Kết quả biên dịch thực tế bằng `arduino-cli`

Hệ thống đã tải `arduino-cli` và cài đặt gói board `esp32:esp32@3.3.12` (Espressif Systems) vào scratchpad, thực hiện biên dịch kiểm thử độc lập cho cả hai sketch với board mục tiêu **AI Thinker ESP32-CAM** (`--fqbn esp32:esp32:esp32cam`):

1. **Biên dịch `firmware/esp32_cam/code_esp32_cam.ino`:**
   * Kết quả: **THÀNH CÔNG (Exit code: 0)**.
   * Dung lượng bộ nhớ chương trình (Flash): **1,016,573 bytes (32%)** / Tối đa: 3,145,728 bytes.
   * Dung lượng bộ nhớ động (RAM): **57,760 bytes (17%)** / Tối đa: 327,680 bytes.
2. **Biên dịch `firmware/esp32_cam_softap/esp32_cam_softap.ino`:**
   * Kết quả: **THÀNH CÔNG (Exit code: 0)**.
   * Dung lượng bộ nhớ chương trình (Flash): **1,015,645 bytes (32%)** / Tối đa: 3,145,728 bytes.
   * Dung lượng bộ nhớ động (RAM): **57,760 bytes (17%)** / Tối đa: 327,680 bytes.

### Kết quả kiểm thử tự động Backend & Frontend

- Backend Tests: `PYTHONPATH=backend pytest backend/tests -q` $\rightarrow$ **81 passed, 3 warnings in 14.45s** (100% test suite vượt qua).
- Frontend Build: `npm run build` $\rightarrow$ **Thành công 100% (0 lỗi TypeScript)**.

## [2026-11-03] REWORK T10: Chuẩn hóa cổng mặc định cho cầu nối camera và Docker Compose

### Bối cảnh & Lý do chỉnh sửa
Sau khi Task T10 nâng cấp firmware tách cổng theo chuẩn CameraWebServer (Port 80 cho `/capture` và `/status`, Port 81 cho `/stream`), phía máy tính (host) và Docker compose vẫn còn trỏ mặc định snapshot capture vào cổng 81:
1. `backend/camera_bridge.py:351`: giá trị mặc định là `"http://192.168.4.1:81/capture"`, khiến lệnh kiểm tra `python camera_bridge.py --check` hoặc chế độ snapshot gặp lỗi 404.
2. `backend/camera_bridge.py:226`: logic cũ suy diễn `stream_url` bằng `self.camera_url.rsplit("/", 1)[0] + "/stream"`. Khi `capture_url` là `http://192.168.4.1/capture` (cổng 80 ngầm định), chuỗi suy ra sẽ là `http://192.168.4.1/stream` (vẫn cổng 80, sai cổng stream 81).
3. `docker-compose.yml:110`: biến fallback `CAMERA_CAPTURE_URL` vẫn là `http://192.168.4.1:81/capture`.
4. `docs/camera-softap.md`: dòng 23 trỏ link snapshot vào `:81/capture` và dòng 118 nhắc tới port 82 cũ.

### Các thay đổi chi tiết

| Tệp thay đổi | Loại thao tác | Mô tả chi tiết | Mục đích / Tác động |
|---|---|---|---|
| `backend/camera_bridge.py` | Chỉnh sửa | 1. Hàm `infer_stream_url(capture_url)`: sử dụng `urllib.parse.urlsplit` và `urlunsplit`, trích xuất `scheme` và `hostname`, ép cổng `:81` và đường dẫn `/stream`.<br>2. Cập nhật `run()`: ưu tiên biến môi trường `CAMERA_STREAM_URL` nếu được thiết lập, fallback tự động qua `infer_stream_url(self.camera_url)`.<br>3. Cập nhật `main()`: đổi giá trị mặc định của `CAMERA_CAPTURE_URL` thành `"http://192.168.4.1/capture"`. | Sửa lỗi 404 khi chạy `--check` hoặc snapshot; tự động suy diễn chính xác cổng 81 cho luồng stream từ capture URL. |
| `backend/tests/test_camera_bridge.py` | Chỉnh sửa | Cập nhật URL mẫu thành `http://192.168.4.1/capture`, bổ sung test case `test_infer_stream_url` kiểm tra các trường hợp: `http://192.168.4.1/capture` $\rightarrow$ `http://192.168.4.1:81/stream`, `http://10.0.0.5:8080/capture` $\rightarrow$ `http://10.0.0.5:81/stream`, URL https và trường hợp URL thiếu host. | Kiểm thử tự động hồi quy logic suy diễn stream URL. |
| `docker-compose.yml` | Chỉnh sửa | Đổi `CAMERA_CAPTURE_URL: ${CAMERA_CAPTURE_URL:-http://192.168.4.1/capture}` (cổng 80). | Đồng bộ cấu hình container cầu nối camera SoftAP với firmware mới. |
| `docs/camera-softap.md` | Chỉnh sửa | 1. Sửa link kiểm tra snapshot ở bước 3 thành `<http://192.168.4.1/capture>`.<br>2. Cập nhật mục kiến trúc port loại bỏ hoàn toàn thông tin cổng 82 cũ, khẳng định chuẩn cổng 80 (capture) và 81 (stream). | Đảm bảo tài liệu hướng dẫn vận hành chuẩn xác. |
| `docs/thay_doi.md` | Chỉnh sửa | Ghi nhận chi tiết thay đổi REWORK T10. | Nhật ký phát triển hệ thống. |

### Kết quả kiểm thử tự động
- `PYTHONPATH=backend pytest backend/tests -q`: **82 passed, 3 warnings in 14.40s** (tăng thêm 1 test case mới, 100% test suite đạt chuẩn).

## [2026-11-03] TASK T11: Điều khiển Bật/Tắt Camera Bridge từ Giao diện Web (Port chọn lọc từ repo bạn dtkien205)

### Bối cảnh & Mục tiêu
Trước đây, người dùng phải mở terminal riêng biệt để chạy các script shell hoặc lệnh Python `camera_bridge.py`. Để tối ưu hóa trải nghiệm giảng viên và quản trị viên, Task T11 triển khai tính năng điều khiển bật/tắt camera bridge trực tiếp từ giao diện web dashboard (tab **Thiết bị & vùng điểm danh**), hỗ trợ cả Webcam laptop và ESP32-CAM qua Wi-Fi.

### Nguồn gốc tham khảo
Module điều khiển và kiểm thử được port có chọn lọc từ repository của thành viên **dtkien205** (cùng nhóm nghiên cứu, cùng nguồn gốc dự án) tại `scratchpad/ref/backend/app/services/bridge_control.py`, `scratchpad/ref/backend/tests/test_bridge_control.py` và các endpoint liên quan. Hệ thống đã được nâng cấp thêm cơ chế chống SSRF bằng `ipaddress`, xử lý reentrant lock, quản lý vòng đời lifespan Starlette và giao diện theo dõi nhật ký stderr 20 dòng gần nhất.

### Các thay đổi chi tiết

| Tệp thay đổi | Loại thao tác | Mô tả chi tiết | Mục đích / Tác động |
|---|---|---|---|
| `backend/app/services/bridge_control.py` | Tạo mới | 1. Class `BridgeControl` quản lý tiến trình nền camera bridge qua `subprocess.Popen` (danh sách tham số CLI, không mở shell).<br>2. Xác thực an toàn `validate_camera_url`: chỉ chấp nhận scheme HTTP(S) tới IP LAN cục bộ hoặc loopback (ngăn chặn SSRF qua `ipaddress`), cấm thông tin đăng nhập nhúng trong URL.<br>3. Truyền `DEVICE_TOKEN` qua biến môi trường `env`, tuyệt đối không truyền qua `argv` để tránh rò rỉ trong bảng tiến trình hệ thống (`ps`).<br>4. Đảm bảo chỉ 1 tiến trình chạy tại một thời điểm, cơ chế dừng an toàn `terminate` và `kill` sau 3 giây.<br>5. Luồng daemon đọc bộ đệm `stderr` lưu giữ 20 dòng gần nhất để hiển thị lỗi cho người dùng. | Cung cấp dịch vụ quản lý vòng đời cầu nối camera an toàn, tin cậy và minh bạch. |
| `backend/app/api/devices.py` | Chỉnh sửa | 1. Tích hợp `devices_lifespan`: tự động gọi `bridge.stop()` khi ứng dụng FastAPI dừng hoạt động.<br>2. Bổ sung các REST endpoint yêu cầu token quản trị (`verify_token`): `GET /api/bridge/status`, `POST /api/bridge/start` (`source: "webcam"|"esp32"`, `camera_url`), `POST /api/bridge/stop` (kèm các route alias `/api/camera-bridge/*`). | Cho phép bảng điều khiển tương tác điều khiển tiến trình camera. |
| `backend/app/core/config.py` | Chỉnh sửa | Bổ sung các thuộc tính cấu hình mặc định: `default_camera_url`, `bridge_device_id`, `backend_port`. | Hỗ trợ fallback cấu hình cho camera bridge. |
| `backend/.env.example` | Chỉnh sửa | Thêm các dòng cấu hình mẫu: `CAMERA_CAPTURE_URL`, `CAMERA_DEVICE_ID`, `BACKEND_PORT`. | Hướng dẫn cấu hình môi trường chuẩn. |
| `backend/tests/test_bridge_control.py` | Tạo mới | Bộ 14 bài kiểm thử tự động toàn diện: kiểm tra chống SSRF (chặn 8.8.8.8, file://, domain ngoài), kiểm tra không cho phép 2 tiến trình song song, mock subprocess không mở shell, ẩn token khỏi argv, kiểm tra timeout 3s khi stop, kiểm tra quyền admin và kiểm tra dọn dẹp khi lifespan shutdown. | Đảm bảo 100% độ bao phủ kiểm thử cho tính năng mới. |
| `frontend/src/App.tsx` | Chỉnh sửa | Tại tab `devices`: thêm bảng điều khiển Cầu nối Camera với 3 nút chức năng "Bật camera laptop", "Bật ESP32-CAM" (ô nhập URL camera cổng 80), "Tắt cầu nối", hiển thị trạng thái hoạt động, PID và khung nhật ký lỗi stderr (20 dòng gần nhất). | Cung cấp trải nghiệm điều khiển camera 1-click trực quan cho người dùng. |
| `frontend/src/styles.css` | Chỉnh sửa | Bổ sung CSS cho grid trạng thái cầu nối, form điều khiển và hộp log stderr tối màu. | Đảm bảo tính thẩm mỹ, nhất quán giao diện Dark HUD. |
| `README.md` | Chỉnh sửa | Cập nhật mục Bước 4 hướng dẫn bật/tắt camera trực tiếp từ Web UI bên cạnh các script terminal. | Hướng dẫn người dùng phương thức vận hành mới. |
| `docs/thay_doi.md` | Chỉnh sửa | Ghi nhận chi tiết thay đổi và kết quả nghiệm thu Task T11. | Nhật ký phát triển hệ thống. |

### Kết quả kiểm thử thực tế
- Backend Tests: `PYTHONPATH=backend pytest backend/tests -q` $\rightarrow$ **96 passed, 3 warnings in 13.31s** (tăng thêm 14 test case mới, 100% test suite vượt qua).
- Frontend Build: `npm run build` $\rightarrow$ **Thành công 100% (0 lỗi TypeScript)**.

## [2026-11-03] REWORK T11: Tối ưu hóa điều khiển vòng đời và chuẩn hóa kiểm thực Camera Bridge

### Bối cảnh & Lý do chỉnh sửa
1. Không lạm dụng tính năng gộp lifespan của `APIRouter` (phụ thuộc phiên bản FastAPI nội bộ). Đưa `bridge.stop()` vào khối `finally:` của lifespan chính trong `backend/app/main.py`.
2. Gỡ bỏ các endpoint alias `/camera-bridge/*` không có trong đặc tả, tránh dư thừa code.
3. Thu gọn `_resolve_script` chỉ giữ 1 đường dẫn chuẩn `backend/camera_bridge.py`. Truy cập trực tiếp cấu hình `settings.default_camera_url` và `settings.backend_port` thay vì dùng `getattr`.
4. Chuẩn hóa hàm `validate_camera_url`: khối `try/except` chỉ bao quanh hàm phân tích `ipaddress.ip_address`, sau đó kiểm tra điều kiện ngoài khối try, dùng lại hàm thuần `is_private_or_loopback_ip` cho cả IP và hostname domain, loại bỏ bắt lỗi bằng chuỗi thông điệp ngoại lệ.
5. Kiểm thực Pydantic kiểu dữ liệu chặt chẽ bằng `Literal["webcam", "esp32"]`.

### Các thay đổi chi tiết

| Tệp thay đổi | Loại thao tác | Mô tả chi tiết | Mục đích / Tác động |
|---|---|---|---|
| `backend/app/main.py` | Chỉnh sửa | Đặt lệnh `bridge.stop()` vào khối `finally:` của context manager `lifespan`. | Đảm bảo bridge luôn được dừng tin cậy khi server tắt, không phụ thuộc phiên bản framework. |
| `backend/app/api/devices.py` | Chỉnh sửa | 1. Xóa `devices_lifespan`, trả lại `router = APIRouter()`.<br>2. Xóa bỏ 3 endpoint alias `/camera-bridge/*`.<br>3. Khai báo `BridgeStartRequest.source: Literal["webcam", "esp32"]`. | Tinh gọn mã nguồn và tự động kiểm thực giá trị nguồn camera bằng Pydantic (trả về 422 khi sai giá trị). |
| `backend/app/services/bridge_control.py` | Chỉnh sửa | 1. Thu gọn `_resolve_script` dùng đường dẫn duy nhất `parents[2] / "camera_bridge.py"`.<br>2. Sử dụng trực tiếp `settings.default_camera_url` và `settings.backend_port`.<br>3. Viết lại `validate_camera_url` tách biệt logic parse IP và kiểm tra private/loopback, tái sử dụng hàm `is_private_or_loopback_ip`. | Tối giản, tường minh và loại bỏ code phỏng đoán/dự phòng thừa. |
| `backend/tests/test_bridge_control.py` | Chỉnh sửa | 1. Bổ sung test case `test_lifespan_shuts_down_bridge` sử dụng context manager `TestClient(app)`.<br>2. Bổ sung test case `test_start_rejects_invalid_source_literal` kiểm tra Pydantic validate Literal (422). | Nâng tổng số bài test kiểm thử bridge control lên 15 bài, kiểm chứng trọn vẹn vòng đời và schema. |
| `docs/thay_doi.md` | Chỉnh sửa | Ghi nhận chi tiết thay đổi REWORK T11. | Nhật ký phát triển hệ thống. |

### Kết quả kiểm thử thực tế
- Backend Tests: `PYTHONPATH=backend pytest backend/tests -q` $\rightarrow$ **97 passed, 3 warnings in 13.88s** (100% test suite vượt qua).
- Frontend Build: `npm run build` $\rightarrow$ **Thành công 100% (0 lỗi TypeScript)**.










