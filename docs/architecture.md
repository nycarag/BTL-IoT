# Kiến trúc triển khai

```text
NÚT CAMERA
  ├─ ESP32-CAM (Firmware tách cổng: 80 Snapshot/Control, 81 Stream MJPEG)
  ├─ Điện thoại chạy IP camera (start_phone.sh)
  └─ Webcam laptop (dự phòng)
       | (Frame video / ảnh chụp qua HTTP)
       v
GATEWAY / COORDINATOR (Laptop / FastAPI)
  ├─ token thiết bị (X-Device-Token), assignment và phiên đang mở
  ├─ rate-limit / một ảnh đang xử lý mỗi device
  ├─ giới hạn 5 MiB, JPEG/PNG, 4 MP; decode JPEG 1 lần duy nhất cho toàn pipeline
  ├─ YuNet face detector (ONNX, score ≥ 0.8) kèm Haar fallback + một mặt trong ROI + size/sharpness + clamp bbox
  ├─ geometric stability IoU qua N frame liên tiếp (stable_frames=3, gap=2.0s) theo device/session
  ├─ active liveness EAR (Eye Aspect Ratio, dlib 68 landmarks) trên preview stream (~10 Hz)
  ├─ MiniFASNetV2 ONNX / CPU (crop 80x80 dịch chuyển biên, BGR float32 0..255) → real softmax index 1 ≥ 0.45
  ├─ dlib embedding 128D thô (đa mẫu 1-5 ảnh) → khoảng cách Euclid đa mẫu tối thiểu + ambiguity margin
  ├─ SQLite transaction: BEGIN IMMEDIATE recheck phiên/lớp/assignment/enrollment
  ├─ UNIQUE(session_id, student_id), đúng giờ/đi muộn
  ├─ audit + WebSocket xác thực → React dashboard (Canvas HTML5 vẽ box overlay)
  └─ Tác vụ nền cloud_sync (đọc con trỏ SQLite, gom lô gửi bù)
       | (POST JSON HTTP 302: điểm danh + thiết bị)
       v
CLOUD (Google Sheets + Apps Script)
  ├─ Code.gs (doPost xử lý gom dữ liệu, script lock)
  ├─ Bảng lưu trữ: DiemDanh, ThietBi
  └─ Bảng phân tích tự động: ThongKeBuoi, ThongKeSV
```

## Dữ liệu và quyền

- `classes`, `students`: hồ sơ và lớp hiện tại; `attendance_sessions`: draft → open → closed, không mở lại phiên đóng.
- `devices`, `device_configs`: heartbeat và assignment/ROI. Status online/offline tính từ TTL khi đọc API, không mặc định online mãi.
- `face_references`: embedding JSON (mảng vector thô 128D đa mẫu), consent timestamp, giảng viên đăng ký; không public embedding qua API.
- `attendance`: unique cặp phiên/sinh viên; verification `face+pad:...` hoặc `manual:<username>`.
- `liveness_events`: kết quả/reason/thời gian/mã SV nếu có; endpoint trả tối đa 200 sự kiện mới nhất. Chưa có job tự xóa log; cần chính sách retention ở môi trường triển khai.

Giảng viên dùng signed bearer token HMAC-SHA256 có hạn 8 giờ; khóa ký là `SECRET_KEY` cấu hình trong `.env` (tự sinh ngẫu nhiên tạm thời nếu thiếu), thay `SECRET_KEY` sẽ vô hiệu hóa toàn bộ token đã cấp. Thiết bị dùng shared `DEVICE_TOKEN` qua header `X-Device-Token` (prototype, chưa tách token từng camera). WS xác thực ở message đầu, kiểm tra lại khi nhận ping và trước broadcast. CORS khóa cứng theo regex dải IP nội bộ và origin tin cậy. Giới hạn ảnh và rate-limit nội bộ không thay thế reverse-proxy/network hardening khi public Internet.

## Enrollment và quyết định

Đăng ký khuôn mặt là thao tác giảng viên có consent; cần kiểm tra trực tiếp đúng người. Chấp nhận 1 đến 5 ảnh chân dung (đa mẫu), trích xuất vector thô 128D của dlib và lưu trữ dưới dạng mảng JSON `[[...], [...]]`, tuyệt đối không chuẩn hóa L2 sớm. Có endpoint thu hồi embedding mà không xóa lịch sử. Không nạp ảnh theo filename từ `data/faces` nữa.

Pipeline dùng cùng bbox đã qua ROI cho PAD và recognition, không tự phát hiện lại một người khác. Ảnh JPEG được giải mã duy nhất một lần ở đầu pipeline và tái sử dụng cho tất cả mô hình phía sau. Active liveness (phát hiện chớp mắt qua EAR bằng dlib 68 landmarks) xử lý bất đồng bộ không chặn luồng preview (tối đa 10 Hz) với adaptive baseline trung vị. Khi cổng AI nhận diện, backend kiểm tra đã có chớp mắt hợp lệ trong cửa sổ thời gian gần nhất (mặc định 5s) và cùng vị trí khuôn mặt; sau khi ghi nhận điểm danh thành công thì chớp mắt được tiêu thụ (consume) để không dùng lại cho các frame kế tiếp. Lưu ý: cơ chế chớp mắt chỉ chống ảnh tĩnh/ảnh in; video quay sẵn có cảnh chớp mắt phát lại trên màn hình vẫn qua được lớp này và việc ngăn chặn hoàn toàn phụ thuộc vào mô hình PAD phát hiện màn hình.

Mô hình PAD MiniFASNetV2 xử lý tensor NCHW `(1, 3, 80, 80)` chuẩn BGR float32 0..255, dịch chuyển box vào trong biên ảnh thay vì cắt cụt khi ở sát mép để bảo toàn tỷ lệ khuôn mặt; chỉ chấp nhận khi output class 1 (Real) đạt ngưỡng `pad_real_threshold = 0.45`. Nhận diện khuôn mặt tính khoảng cách Euclid vector hóa giữa probe và từng vector mẫu của sinh viên, lấy khoảng cách nhỏ nhất (`min_dist`); best match vượt ngưỡng `0.52` hoặc khoảng cách an toàn với người thứ hai nhỏ hơn `0.05` bị từ chối. Hệ thống tự động cảnh báo log nếu phát hiện embedding cũ đã bị chuẩn hóa L2 (chuẩn độ dài xấp xỉ 1.0) để nhắc giảng viên cho sinh viên đăng ký lại.

Stability chỉ là liên tục hình học theo IoU và khoảng cách thời gian (3 frame trong 2 giây), không chứng minh cùng danh tính hoặc hướng đi. Một người ngoài ROI không được chọn; nhiều người trong ROI bị reject. Thay camera/độ phân giải/góc lắp phải hiệu chỉnh lại.

## Điều khiển Camera Bridge từ Web & Chống SSRF

Dịch vụ `BridgeControl` (`backend/app/services/bridge_control.py`) quản lý tiến trình nền `camera_bridge.py` trực tiếp từ Web Dashboard qua các REST endpoint có xác thực admin (`/api/bridge/status`, `/api/bridge/start`, `/api/bridge/stop`):
- Hỗ trợ chọn nguồn: webcam máy tính cục bộ (`source="webcam"`) hoặc ESP32-CAM qua mạng (`source="esp32"` kèm URL camera).
- Chống SSRF: hàm `validate_camera_url` xác thực chặt chẽ URL camera, chỉ chấp nhận scheme HTTP/HTTPS trỏ về địa chỉ IP thuộc dải private LAN hoặc loopback (thông qua `ipaddress` và kiểm tra DNS getaddrinfo), cấm tuyệt đối IP public, scheme lạ (`file://`) hoặc credential nhúng trong URL.
- Quản lý vòng đời an toàn: token bảo mật `DEVICE_TOKEN` chỉ truyền qua biến môi trường `env`, không truyền qua `argv` dòng lệnh; tiến trình bridge tự động dừng an toàn khi máy chủ FastAPI shutdown qua Starlette lifespan.

## Tính nhất quán

SQLite foreign keys bật, busy timeout 5s. Điểm danh và đổi trạng thái phiên dùng write transaction `BEGIN IMMEDIATE`. Trước insert đọc lại phiên, lớp, assignment và tồn tại enrollment; unique constraint chặn duplicate cả khi request tranh chấp. Duplicate trả created=false, không ghi thêm attendance. Mở/đóng phiên, liveness và attendance phát sự kiện WS; frontend polling phục hồi khi WS mất.

Image inference chạy threadpool để không giữ event loop, mỗi device chỉ xử lý một frame; broadcast có timeout và loại kết nối lỗi. Luồng camera stream WebSocket (`/ws/devices/{id}/camera`) phát metadata JSON (`type: "meta"`) và binary JPEG theo nhịp ACK `"next"`; phía client React vẽ bounding box trực tiếp trên Canvas HTML5 theo tỷ lệ contain chuẩn, loại bỏ hoàn toàn việc vẽ đè lên ảnh ở backend giúp giảm tải CPU máy chủ.

## Tầng cloud và đồng bộ từ gateway

Tầng cloud bổ sung khả năng lưu trữ bản sao điểm danh và tự động phân tích dữ liệu chuyên cần trên Google Sheets thông qua Google Apps Script (`cloud/apps_script/Code.gs`), nâng hệ thống từ mô hình khép kín tại chỗ lên cấp độ IoT Level 5 (xem chi tiết tại [docs/cloud.md](cloud.md)).

Cơ chế đồng bộ hoạt động theo nguyên tắc:
- Tác vụ nền `cloud_sync` chạy định kỳ ngoài luồng sự kiện chính (`asyncio.to_thread`), không gây nghẽn luồng nhận diện camera.
- Dùng hai transaction SQLite ngắn: đọc con trỏ và dữ liệu cần gửi, giải phóng kết nối DB trong lúc gọi mạng ra cloud, sau đó mở lại transaction ngắn để cập nhật con trỏ `cloud_last_attendance_id` trong `app_settings`.
- Mất kết nối mạng không làm mất dữ liệu: con trỏ giữ nguyên và gateway tự động gửi bù khi có mạng trở lại. Cloud dựa vào `event_id` duy nhất để tự động lọc bỏ các bản ghi trùng lặp.
- Quản trị viên theo dõi trạng thái và kích hoạt đồng bộ tức thời qua hai endpoint `/api/cloud/status` và `/api/cloud/sync-now`.

## Docker và giới hạn

Backend UID 10001, frontend unprivileged, filesystem read-only + tmpfs. SQLite/embedding ở volume; model mount read-only. Không nhúng secrets/biometric vào image. Xem docker.md để build và backup.

Phần mềm không có đánh giá thực tế đủ để khẳng định chống giả mạo ảnh in/replay, FAR/FRR hoặc latency ESP32. Mặc định calibrated=false. Thiếu/lỗi AI không được ghi tự động; dùng xác minh trực tiếp thủ công có audit và nhãn riêng. SQLite/embedding hiện không mã hóa tại ứng dụng, phải bảo vệ ổ đĩa và backup.

## Giới hạn đã biết

1. **Active Liveness (Phát hiện chớp mắt qua EAR):**
   - **Chỉ ngăn chặn ảnh tĩnh và ảnh in** (photo attack) không có chuyển động mắt.
   - **Không ngăn chặn được video replay có cảnh chớp mắt**: Nếu kẻ tấn công phát video quay sẵn người thật đang chớp mắt trên màn hình điện thoại/máy tính bảng, thuật toán EAR vẫn tính toán và ghi nhận chớp mắt thành công.
   - **Phát hiện màn hình phụ thuộc vào PAD MiniFASNet**: Mô hình PAD đơn lẻ chưa đủ tin cậy trước màn hình chất lượng cao hoặc vân moiré mờ (thực nghiệm Task T06 cho thấy ảnh moiré giả lập vẫn đạt 0.8746 so với ngưỡng pass 0.45). Video replay chỉ bị chặn nếu PAD bắt được texture màn hình.
   - **Chưa kiểm chứng chớp mắt trên camera phần cứng thực tế**: Ngưỡng nhắm mắt thích ứng mới chỉ đo nghiệm offline baseline mắt mở trên ảnh tĩnh (`obama.jpg` = 0.2277). Khi demo nếu gặp hiện tượng từ chối oan do camera góc nghiêng, khoảng cách xa hoặc FPS preview thấp, có thể tạm tắt bằng `LIVENESS_MODE=off` hoặc căn chỉnh `LIVENESS_CLOSED_RATIO`.
2. **Nhận diện khuôn mặt:**
   - Không chống được deepfake chuyên sâu hoặc video replay chất lượng cao chỉ bằng phần mềm mã nguồn mở đơn lẻ này.
   - Chưa đo tỷ lệ lỗi nhận diện sai / từ chối sai (FAR/FRR) trên tập dữ liệu sinh viên quy mô lớn.
   - Toàn bộ pipeline AI sau đợt nâng cấp mới chỉ được kiểm chứng trên tập ảnh mẫu công khai qua mạng nội bộ và unit tests tự động, chưa thử nghiệm trực tiếp trên phần cứng ESP32-CAM và sóng Wi-Fi thực tế.
