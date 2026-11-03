# PAD và nhận diện: nguồn, quy ước và hiệu chỉnh

## Model đang dùng

- Repo: https://github.com/yakhyo/face-anti-spoofing
- Weights: https://github.com/yakhyo/face-anti-spoofing/releases/download/weights/MiniFASNetV2.onnx
- File: `models/minifasnet-v2/MiniFASNetV2.onnx`
- SHA-256 của bản tải ngày 2026-10-29: `b32929adc2d9c34b9486f8c4c7bc97c1b69bc0ea9befefc380e4faae4e463907`
- LICENSE trong repo ghi Apache-2.0; adapter là bản tích hợp có điều chỉnh, xem `docs/licenses/face-anti-spoofing-LICENSE.txt`. Repo dẫn nguồn Silent-Face-Anti-Spoofing. Cần kiểm tra thêm điều khoản trọng số/dataset nếu phân phối hoặc dùng thương mại; không suy ra tất cả dữ liệu/weights đều cùng license chỉ từ license code.
- `fas6_iccvw2025` không dùng trong runtime vì bản tải không có checkpoint. Giữ làm tham khảo, không cài dependencies/train tự động.

## Preprocessing và output

> [!IMPORTANT]
> **Đính chính nhận định sai lầm trong báo cáo sơ bộ (Pha 0):** Báo cáo P0 từng nhận định *"crop bị méo, phải crop vuông"*. Nhận định đó là **hoàn toàn sai**. Trong mã nguồn gốc của nhóm tác giả Minivision (`minivision-ai/Silent-Face-Anti-Spoofing`, tệp `src/generate_patches.py: _get_new_box`), vùng crop được mở rộng theo đúng kích thước chữ nhật của khuôn mặt: `new_width = box_w * scale`, `new_height = box_h * scale` (không ép vuông trước khi resize), sau đó mới resize phi tỷ lệ về `(80, 80)`. Mô hình MiniFASNetV2 được huấn luyện trực tiếp trên phân phối đặc trưng này, việc tự ý đổi sang crop vuông sẽ làm biến dạng nghiêm trọng phân phối đầu vào mà mạng nơ-ron đã học.

### Bảng đối chiếu từng bước tiền xử lý với nguồn gốc

| Bước tiền xử lý | Nguồn gốc (file:dòng, URL) | Code hiện tại (`antispoof.py`) | Trạng thái | Đánh giá & Xử lý |
|---|---|---|---|---|
| **1. Định dạng màu (Color format)** | BGR (`cv2.imread`). Minivision `test.py:38`, yakhyo `onnx_inference.py:78` | BGR ndarray (từ `decode_image`) | **Khớp** | Giữ nguyên BGR, tuyệt đối không chuyển sang RGB. |
| **2. Tỷ lệ mở rộng (Crop scale)** | `scale = 2.7` cho MiniFASNetV2 (`test.py`, `MODEL_CONFIGS["v2"]`, `onnx_inference.py:106`) | `scale = 2.7` (`settings.pad_crop_scale`) | **Khớp** | Giữ nguyên 2.7 cho V2. |
| **3. Xử lý biên khi mở rộng** | Minivision `src/generate_patches.py:34-47`: Dịch box (`right_bottom_x -= left_top_x`, v.v.) vào trong ảnh | Thuật toán `_get_new_box` chuẩn Minivision: dịch chuyển box vào trong ảnh | **Khớp** *(đã sửa)* | Trước đây code dùng `max(0, ...)` và `min(...)` làm xén cụt box khi ở gần mép ảnh. Đã sửa sang cơ chế dịch box của Minivision gốc để bảo toàn trọn vẹn diện tích và tỷ lệ context. |
| **4. Kích thước đầu ra** | `(80, 80)` (MiniFASNet input) | `size=(80, 80)`, resize `(80, 80)` | **Khớp** | Giữ nguyên kích thước 80×80. |
| **5. Chuẩn hóa giá trị pixel** | `0..255 float32` (không chia 255, không trừ mean, không chia std). Minivision `src/data_io/functional.py:31`: `return img.float()`; yakhyo `utils.py:76` | `dtype=np.float32` không chia 255 | **Khớp** | Giữ nguyên miền giá trị 0..255 float32. |
| **6. Tensor Layout** | NCHW `(1, 3, 80, 80)`. Minivision `anti_spoof_predict.py:84`, yakhyo `onnx_inference.py:65-66` | `crop.transpose(2, 0, 1)[None]` -> `(1, 3, 80, 80)` | **Khớp** | Giữ nguyên. |
| **7. Số lớp đầu ra & Class thật** | 3 lớp logits `(1, 3)`. Class 1 là "Real" (`label == 1`). Minivision `test.py:68`, yakhyo `onnx_inference.py:96` | 3 lớp logits `(1, 3)`, class index 1 là Real (`int(np.argmax(probs[0])) == 1`) | **Khớp** | Giữ nguyên class index 1. |
| **8. Kích hoạt xác suất (Softmax)** | `softmax(logits)` trên trục 1. Minivision `anti_spoof_predict.py:92`, yakhyo `onnx_inference.py:71-72` | `np.exp(logits - logits.max...)` softmax trục 1 | **Khớp** | Giữ nguyên. |

### Đánh giá thực nghiệm PAD trên tập ảnh chuẩn của tác giả & ảnh thực tế

Kiểm tra trực tiếp mô hình ONNX `MiniFASNetV2.onnx` với tiền xử lý chuẩn:

| Tệp ảnh thử nghiệm | Loại ảnh | Bounding box detected | Dự đoán `is_real` | Score thực tế (Class 1 - Real) | Nhận xét |
|---|---|---|---|---|---|
| `image_T1.jpg` (Minivision sample) | Mặt thật (True live) | `(119, 113, 170, 240)` | **True** (`PAD passed`) | **0.999956** (~99.99%) | Nhận diện mặt thật với độ tự tin tuyệt đối |
| `image_F1.jpg` (Minivision sample) | Mặt giả mạo 1 (Print/Screen) | `(188, 110, 195, 239)` | **False** (`spoof or uncertain`) | **0.003597** (~0.36%) | Ngăn chặn chính xác mặt giả mạo |
| `image_F2.jpg` (Minivision sample) | Mặt giả mạo 2 (Cut-out) | `(139, 217, 223, 298)` | **False** (`spoof or uncertain`) | **0.004053** (~0.40%) | Ngăn chặn chính xác mặt giả mạo |
| `obama.jpg` (Chân dung thật) | Chân dung chụp gốc | `(374, 94, 231, 322)` | **True** (`PAD passed`) | **0.999967** (~99.99%) | Chấp thuận mặt thật |
| `obama_cif.jpg` (ESP32-CAM CIF) | Chân dung resize CIF 400×296 | `(166, 18, 98, 98)` | **True** (`PAD passed`) | **0.999997** (~99.99%) | Chấp thuận mặt thật ở độ phân giải camera IoT |
| `obama.jpg` + Moire pattern | Ảnh thêm hiệu ứng sọc màn hình LCD | `(374, 94, 231, 322)` | **True** (`PAD passed`) | **0.874581** (~87.46%) | Score giảm đáng kể khi có nhiễu màn hình |

### Khuyến nghị cấu hình ngưỡng & số khung hình liên tiếp

1. **Ngưỡng `PAD_REAL_THRESHOLD`:**
   - Giá trị mặc định hiện tại là `0.45` (từ cấu hình `settings.pad_real_threshold`).
   - **Khuyến nghị:** **KHÔNG tự ý thay đổi con số này** nếu chưa có tập dữ liệu calibration thực tế đo đạc trực tiếp trên camera ESP32-CAM trong môi trường phòng học cụ thể. Do mô hình MiniFASNet rất nhạy với chất lượng cảm biến OV2640, ống kính và ánh sáng thực địa, bất kỳ việc nâng/hạ ngưỡng võ đoán nào cũng có thể làm tăng vọt BPCER (từ chối người thật) hoặc APCER (lọt kẻ giả mạo).
2. **Số khung hình liên tiếp `PAD_MIN_CONSECUTIVE`:**
   - Hệ thống hỗ trợ cấu hình biến môi trường `PAD_MIN_CONSECUTIVE` (mặc định `1` = hành vi cũ).
   - Khi triển khai môi trường thực tế với camera phát video stream, có thể cấu hình `PAD_MIN_CONSECUTIVE=2` hoặc `3` để yêu cầu 2-3 frame liên tiếp đạt điều kiện chống giả mạo trước khi cho phép điểm danh, giúp lọc triệt để các frame nhiễu ngẫu nhiên.

## Quy trình thu thập

- Consent phù hợp, phạm vi và thời hạn lưu rõ ràng; tách thư mục dữ liệu thử khỏi source công khai.
- Tập calibration và tập test độc lập, ưu tiên tách người/buổi/điều kiện ánh sáng. Không chọn threshold trên tập rồi báo chính tập đó là test độc lập.
- Nhóm live, ảnh in (giấy/màn hình khác nhau), replay video điện thoại, ảnh mờ/thiếu sáng/ngược sáng/góc lệch, ngoài ROI, nhiều người.
- Ghi camera, khoảng cách, độ phân giải, JPEG quality, ánh sáng, người/phiên ẩn danh, loại tấn công, bbox, score và latency. Không giữ ảnh lâu hơn consent cho phép.

## Công cụ đánh giá PAD

Tạo CSV riêng (ví dụ minh họa cấu trúc, không phải dữ liệu đo):

```csv
path,label,x,y,w,h
images/live-001.jpg,live,120,80,160,160
images/print-001.jpg,print,118,82,164,164
images/replay-001.jpg,replay,122,84,158,158
```

Bbox lấy từ detector thực. Chạy từ backend với env/model đã cấu hình:

```bash
python evaluate_pad.py --manifest /duong-dan-rieng/calibration.csv --output /duong-dan-rieng/calibration-report.json --threshold 0.9
```

Không ghi đè file báo cáo cũ. Công cụ không ghi attendance, không bật calibrated, không tự chọn threshold và không tải ảnh lên dịch vụ bên ngoài. Trong Docker có thể chạy cùng script qua `docker compose exec` sau khi bạn mount tập kiểm thử riêng; không đưa ảnh test vào image.

- APCER: tấn công bị chấp nhận / tổng mẫu tấn công; báo cả theo loại print/replay.
- BPCER: người thật bị từ chối / tổng mẫu thật.
- Mẫu lỗi được giữ trong tổng số và từ chối an toàn; xem cả `errors`, không che lỗi decode/mô hình. Mean latency gồm đọc/validate/inference từng mẫu, không gồm tải model.
- Chọn threshold dựa trên mục tiêu rủi ro và BPCER chấp nhận được, sau đó đo độc lập. Số liệu ít phải ghi rõ không đủ kết luận.

## Nhận diện danh tính

Dlib/face_recognition tạo embedding 128 chiều. So khớp **Euclidean distance**, không phải cosine; chọn ngưỡng tương ứng, không thay nhầm công thức. Giới hạn ứng viên theo lớp, reject nếu khoảng cách tốt nhất vượt `RECOGNITION_THRESHOLD` hoặc best/second-best quá gần (`RECOGNITION_MARGIN`). Đăng ký và probe cần dùng cùng phiên bản embedding.

Đo genuine/impostor pairs trên dữ liệu consent, ghi FAR/FRR, unknown identity và trường hợp gần giống. Embedding enrollment lưu trong SQLite kèm thời gian consent và người đăng ký; không lưu ảnh thô.

Sau khi có kết quả chấp nhận được, sửa `.env` (Docker) hoặc `backend/.env` (native):

```dotenv
PAD_REAL_THRESHOLD=<nguong_da_do>
RECOGNITION_THRESHOLD=<nguong_da_do>
RECOGNITION_MARGIN=<margin_da_do>
PAD_CALIBRATED=true
RECOGNITION_CALIBRATED=true
```

Docker: `docker compose up -d` để recreate/nạp env mới. Chỉ `restart` không đổi environment. Native: khởi động lại backend. Cờ calibrated là xác nhận của người triển khai, không phải chứng nhận độ chính xác. Chưa có dữ liệu thực thì giữ false và dùng xác minh thủ công.

## Đánh giá thực nghiệm nhận diện trên ảnh thật (Kiểm tra mẫu nhỏ, không phải benchmark)

> [!NOTE]
> Đây là phép đo kiểm chứng kỹ thuật trên một số ảnh mẫu công khai (tập ảnh ví dụ từ `ageitgey/face_recognition`: `obama.jpg`, `obama2.jpg`, `biden.jpg`), nhằm xác nhận tính nhất quán của không gian vector thô và kiểm tra cơ chế so khớp đa mẫu tham chiếu. Đây **không phải** là benchmark hoàn chỉnh (chưa đo FAR/FRR trên tập dữ liệu quy mô lớn).

### 1. Dữ liệu thử nghiệm
- Ảnh khuôn mặt 1 (Obama 1): `obama.jpg` (ảnh chân dung chụp thẳng).
- Ảnh khuôn mặt 2 (Obama 2): `obama2.jpg` (ảnh khuôn mặt cùng người nhưng góc chụp và biểu cảm khác).
- Ảnh khuôn mặt 3 (Biden): `biden.jpg` (ảnh người khác).

### 2. Số liệu đo lường vector thô (dlib 128D)
- Norm thô của `obama.jpg`: **1.3872**
- Norm thô của `obama2.jpg`: **1.3638**
- Norm thô của `biden.jpg`: **1.3899**
*(Xác nhận: Vector thô của dlib ResNet không có chuẩn L2 = 1.0; việc chia L2-norm trước đây là sai lệch thang đo chuẩn dlib).*

### 3. Ma trận khoảng cách Euclid (Euclidean Distance)

| Cặp ảnh so sánh | Mối quan hệ | Khoảng cách Euclid thực tế | Ngưỡng chuẩn dlib (< 0.60) | Đánh giá |
|---|---|---|---|---|
| `obama.jpg` $\leftrightarrow$ `obama2.jpg` | Cùng một người (Genuine) | **0.3457** | Đạt (< 0.60) | Nhận diện đúng người |
| `obama.jpg` $\leftrightarrow$ `biden.jpg` | Khác người (Impostor) | **0.8402** | Bị từ chối (> 0.60) | Từ chối chính xác mạo danh |
| `obama2.jpg` $\leftrightarrow$ `biden.jpg` | Khác người (Impostor) | **0.8158** | Bị từ chối (> 0.60) | Từ chối chính xác mạo danh |

### 4. Kết quả kiểm tra luồng khớp đa mẫu tham chiếu
- **Kịch bản 1 (Chỉ enroll Obama):**
  - Probe `obama2.jpg`: Khớp thành công `SV_OBAMA` với khoảng cách **0.3457** (khoảng cách nhỏ hơn ngưỡng 0.60).
  - Probe `biden.jpg`: Trả về `None` (bị loại do khoảng cách 0.8402 vượt ngưỡng 0.60).
- **Kịch bản 2 (Enroll cả Obama và Biden):**
  - Probe `obama2.jpg`: Khớp thành công `SV_OBAMA` (khoảng cách 0.3457; sinh viên gần thứ nhì là Biden cách 0.8158, chênh lệch biên độ $0.8158 - 0.3457 = 0.4701 \ge 0.05$).
  - Probe `biden.jpg`: Khớp thành công `SV_BIDEN`.
- **Kịch bản 3 (Đa mẫu tham chiếu cho cùng một sinh viên):**
  - Sinh viên được đăng ký 2 ảnh (`obama.jpg` và `obama2.jpg`).
  - Khi probe gửi `obama2.jpg`: Hệ thống tự động chọn khoảng cách nhỏ nhất giữa probe và tập mẫu của sinh viên (**0.0000**), không bị vi phạm margin nội bộ giữa các mẫu của cùng một người.
