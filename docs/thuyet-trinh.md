# Báo cáo thuyết trình bài tập lớn IoT (Nhóm 05)

Học phần: IoT và ứng dụng (INT14149) · Nhóm lớp tín chỉ: INT14149-20261-CT02 · Nhóm: 05 · Lớp sinh hoạt: D23CTAT01-B
Đề tài: Hệ thống Kiosk Điểm danh Sinh viên Thông minh AIoT (Edge Camera SoftAP + MiniFASNetV2 PAD + dlib Face Recognition)

## 1. Luồng xử lý dữ liệu

```
ESP32-CAM / Webcam ──(MJPEG/JPEG)──> Camera Bridge ──(HTTP POST)──> FastAPI
  │ 1. Kiểm tra ảnh và tần suất gửi (JPEG/PNG, interval 0.3s)
  │ 2. Dò mặt lớn nhất trong ROI (YuNet, fallback Haar; độ nét Laplacian >= 20)
  │ 3. Cổng ổn định hình học (>= 3 frame liên tiếp, IoU >= 0.6, khoảng cách <= 2.0s)
  │ 4. Chống giả mạo PAD (MiniFASNetV2 ONNX, scale 2.7, ngưỡng thật >= 0.45)
  │ 5. Kiểm tra chớp mắt chủ động (EAR dlib 68 mốc, nếu liveness bật)
  │ 6. So khớp danh tính (dlib vector 128D, khoảng cách Euclid <= 0.52, margin 0.05)
  └── 7. Ghi nhận SQLite WAL, phát chuông bíp và gửi thông báo WebSocket Kiosk
```

## 2. Thông số kỹ thuật các thành phần

| Thành phần | Công nghệ | Thông số cấu hình chính |
|---|---|---|
| Thiết bị thu hình | ESP32-CAM SoftAP / Webcam | Wi-Fi SoftAP 192.168.4.1 (cổng 80 capture, cổng 81 stream), interval 0.3s |
| Dò khuôn mặt | YuNet (fallback Haar Cascade) | Ngưỡng điểm 0.8, diện tích mặt >= 3%, độ nét Laplacian >= 20 |
| Cổng ổn định | Theo dõi liên tục đa khung | 3 frame liên tiếp, IoU >= 0.6, khoảng cách giữa 2 frame <= 2.0s |
| Chống giả mạo | MiniFASNetV2 ONNX | Tensor (1, 3, 80, 80), hệ số cắt 2.7, ngưỡng khuôn mặt thật >= 0.45 |
| Nhận diện khuôn mặt | Mô hình dlib (vector 128D thô) | Khoảng cách Euclid <= 0.52, khoảng cách an toàn ứng viên nhì >= 0.05 |
| Kiểm tra chớp mắt | Thuật toán EAR (dlib 68 mốc) | Ngưỡng nhắm mắt 0.75 trung vị, cửa sổ 5.0s, tần số preview tối đa 10.0 Hz |
| Lưu trữ và cảnh báo | SQLite WAL + Audio HMI | Giao dịch BEGIN IMMEDIATE chống tranh chấp, chuông bíp phát qua loa máy chủ |

## 3. Kịch bản trình diễn

- Bước 1 (Quét mặt thật sinh viên): Sinh viên nhìn camera và chớp mắt một lần; sau 3 frame ổn định, PAD đạt và có chớp mắt, hệ thống nhận diện đúng mã sinh viên, ghi nhận có mặt, phát chuông bíp và Kiosk hiển thị trạng thái điểm danh thành công.
- Bước 2 (Thử nghiệm tấn công giả mạo): Đưa ảnh chân dung trên điện thoại hoặc giấy in trước camera; MiniFASNetV2 phát hiện bề mặt giả mạo (điểm số < 0.45), hệ thống từ chối với lý do "spoof or uncertain PAD score", không phát chuông và không ghi nhận điểm danh; nếu PAD bỏ sót, ảnh tĩnh vẫn bị chặn ở bước chớp mắt với lý do "liveness: blink required".
- Bước 3 (Quét lại sinh viên đã có mặt): Sinh viên bước vào quét lại; hệ thống nhận diện đúng danh tính nhưng xác định đã ghi danh trước đó, Kiosk hiển thị trạng thái đã có mặt, không phát lại chuông bíp và không tạo bản ghi mới.

## 4. Câu hỏi thường gặp khi bảo vệ

- Câu 1: Tại sao không gắn còi chip buzzer và đèn LED trực tiếp trên mạch ESP32-CAM?
  Trả lời: Hệ thống được thiết kế để ESP32-CAM chỉ chụp và gửi ảnh, phản hồi (bíp qua loa máy chủ và giao diện Kiosk) nằm ở phía máy tính nên không cần thêm linh kiện vào mạch.
- Câu 2: Nếu phòng học không có Wi-Fi hoặc mạng trường bị chập chờn thì xử lý thế nào?
  Trả lời: ESP32-CAM tự phát mạng Wi-Fi SoftAP cục bộ (192.168.4.1), máy tính kết nối trực tiếp vào mạng này nên hệ thống hoạt động độc lập với hạ tầng mạng ngoài.
- Câu 3: Mục đích của cổng ổn định 3 frame là gì?
  Trả lời: Cổng yêu cầu khuôn mặt giữ vị trí tương đồng (IoU >= 0.6) qua 3 frame liên tiếp để tránh điểm danh người đi lướt qua ngoài ý muốn và loại bỏ frame rung lắc.
- Câu 4: Khi có nhiều người cùng lọt vào khung hình thì hệ thống xử lý ra sao?
  Trả lời: Bộ dò kiểm tra vùng ROI cấu hình sẵn; nếu phát hiện từ hai khuôn mặt trở lên trong ROI, hệ thống từ chối xử lý và yêu cầu chỉ một người vào khung hình.

## 5. Giới hạn hệ thống

Xem chi tiết tại mục [Phạm vi chống gian lận và kiểm chứng](../README.md#phạm-vi-chống-gian-lận-và-kiểm-chứng).
