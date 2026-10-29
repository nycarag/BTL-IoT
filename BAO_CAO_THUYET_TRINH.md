# BÁO CÁO THUYẾT TRÌNH BÀI TẬP LỚN IOT (NHÓM 05)

* **Học phần**: IoT và ứng dụng (INT14149) · Mã lớp học phần: `INT14149-20261-CT02`
* **Lớp sinh hoạt**: D23CTAT01-B · Nhóm: 05
* **Đề tài**: Hệ thống Kiosk Điểm danh Sinh viên Thông minh AIoT (Edge Camera SoftAP + Deep PAD MiniFASNetV2 + ResNet-34 Face Recognition)

---

## 1. Công nghệ sử dụng trong hệ thống

Hệ thống được thiết kế theo kiến trúc **Decoupled 3 tầng độc lập**:

```
[ ESP32-CAM OV2640 ] --(Wi-Fi SoftAP / MJPEG Stream 25-30 FPS)--> [ Laptop / Bridge ]
                                                                          │
  ┌───────────────────────────────────────────────────────────────────────┘
  ▼
[ FastAPI Backend (Python 3.14) ]
  ├── 1. Haar Cascade + Laplacian Sharpness (Lọc mặt, loại bỏ ảnh mờ/lệch)
  ├── 2. Stability Gate (Yêu cầu 3 frame khuôn mặt ổn định, IoU >= 0.6)
  ├── 3. MiniFASNetV2 ONNX (Mạng nơ-ron học sâu kiểm tra chống giả mạo)
  ├── 4. ResNet-34 128D (Trích xuất vector đặc trưng, so khớp Euclidean d <= 0.55)
  ├── 5. SQLite WAL Mode (Giao dịch BEGIN IMMEDIATE chống race condition)
  └── 6. Audio HMI (Loa laptop phát tiếng BÍP xác nhận qua ALSA/PulseAudio)
  ▼
[ React 18 + TypeScript Kiosk ] --(WebSocket luồng ảnh < 100ms)--> Màn hình giám sát Fullscreen
```

### Chi tiết các công nghệ cốt lõi:
1. **Thiết bị biên (Edge Device - ESP32-CAM OV2640)**:
   * Chạy firmware C++ tự phát Wi-Fi Access Point riêng (`ESP32_DIEM_DANH`, IP cố định `192.168.4.1:81/stream`). Không phụ thuộc vào Wi-Fi trường học.
   * Truyền luồng MJPEG độ phân giải CIF (400×296), đạt tốc độ 25–30 FPS, độ trễ mạng dưới 40ms.
   * Cấu hình trực tiếp các thanh ghi cảm biến OV2640: Tự động cân bằng trắng (AWB), tự động phơi sáng (AEC), Gamma Correction và Color Matrix giúp khử ám màu.

2. **Máy chủ xử lý AI (FastAPI Backend)**:
   * **Phát hiện khuôn mặt**: OpenCV Haar Cascade kết hợp bộ tính toán phương sai Laplacian để loại bỏ ảnh mờ chuyển động (sharpness threshold $\ge 20$).
   * **Cổng ổn định (Stability Gate)**: Đo độ giao thoa vùng phát hiện $IoU \ge 0.6$ qua 3 khung hình liên tiếp để tránh nhận diện người đi lướt qua ngoài ý muốn.
   * **Chống giả mạo (PAD)**: Mô hình học sâu **MiniFASNetV2** chạy trên ONNX Runtime CPU.
   * **Nhận diện danh tính**: Mô hình mạng dư **ResNet-34** trích xuất vector embedding 128 chiều, đối chiếu khoảng cách Euclidean với tập dữ liệu sinh viên trong lớp.
   * **HMI âm thanh thay thế còi chip**: Tự động phát âm thanh xác nhận chất lượng cao ra loa máy tính khi nhận diện thành công, không cần hàn còi chip rời vào ESP32.

3. **Giao diện Kiosk giám sát (Frontend React + TypeScript + Vite)**:
   * Màn hình HUD Kiosk chuyên nghiệp, hiển thị trực quan vùng tâm điểm danh (ROI).
   * Luồng xem trực tiếp đẩy qua WebSocket nhị phân (Binary Blob) siêu mượt, độ trễ tổng thể dưới 100ms.
   * Cơ chế **Auto-bind Session**: Tự động liên kết camera với buổi học đang mở, loại bỏ hoàn toàn lỗi cấu hình thủ công.

---

## 2. Vì sao hệ thống chống được giả mạo (Anti-Spoofing)?

### Điểm yếu của phương pháp truyền thống
Các hệ thống điểm danh thông thường chỉ so khớp khuôn mặt 2D hoặc kiểm tra chớp mắt đơn giản:
* Đưa ảnh in trên giấy A4 hoặc ảnh chụp trên màn hình điện thoại / máy tính bảng có thể dễ dàng qua mặt.
* Video quay sẵn người thật chớp mắt cũng đánh lừa được thuật toán kiểm tra chuyển động mắt cơ bản.

### Cơ chế chống gian lận của MiniFASNetV2 trong dự án
Hệ thống sử dụng mạng nơ-ron tích chập chuyên dụng **MiniFASNetV2** được huấn luyện trên hàng trăm nghìn mẫu tấn công thực tế (CASIA-SURF, CelebA-Spoof). Mô hình không nhìn "khuôn mặt có giống không", mà phân tích **bản chất vật lý của bề mặt**:

1. **Phân tích kết cấu vi mô (Micro-texture analysis)**:
   * Da người sống có độ đàn hồi tự nhiên và hiện tượng tán xạ ánh sáng dưới bề mặt (Subsurface Scattering).
   * Màn hình điện thoại và ảnh in có cấu trúc điểm ảnh ma trận LCD/OLED hoặc hạt mực in hoàn toàn khác biệt.
2. **Hiện tượng phản xạ ánh sáng (Specular Reflection) & Viền màn hình**:
   * Kính màn hình điện thoại luôn tạo ra các vệt phản xạ ánh sáng phẳng sắc cạnh.
   * MiniFASNetV2 crop mở rộng vùng khuôn mặt theo tỷ lệ $2.7\times$, quét cả vùng viền tay cầm và khung máy điện thoại để phát hiện dị vật.
3. **Vân Moiré trong miền tần số**:
   * Khi camera quét lại màn hình kỹ thuật số, giao thoa quang học tạo ra các đường vân Moiré tần số cao mà mắt thường khó nhận ra nhưng mạng tích chập phát hiện ngay lập tức.

### Số liệu thực chứng từ cơ sở dữ liệu hệ thống

| Tình huống kiểm thử | Điểm tin cậy thật (`PAD Real Score`) | Kết quả hệ thống |
| :--- | :---: | :--- |
| **Giơ ảnh trên màn hình điện thoại** | **`0.0006 – 0.008`** (Gần bằng 0) | **CHẶN ĐỨNG (REJECTED)**: Báo "Phát hiện nghi vấn giả mạo", không ghi nhận điểm danh. |
| **Quét khuôn mặt người thật** | **`0.46 – 0.96`** (Gấp hàng trăm lần điện thoại) | **CHẤP NHẬN (ACCEPTED)**: Nhận diện danh tính, phát chuông bíp và ghi danh. |

Ngưỡng quyết định được đặt ở mức **`0.45`**, tạo ra khoảng cách an toàn tuyệt đối giữa màn hình giả mạo ($< 0.01$) và người thật ($> 0.45$).

---

## 3. Kịch bản Demo thuyết phục Thầy/Cô (3 bước chuẩn)

Để bài thuyết trình gây ấn tượng mạnh và chứng minh rõ tính năng, nhóm thực hiện demo theo 3 bước:

### Bước 1: Quét mặt thật sinh viên lần đầu (Đạt điểm nhanh)
* **Thao tác**: Sinh viên bước vào trước camera ESP32-CAM trong cự ly 40–80cm, nhìn thẳng.
* **Hiện tượng xảy ra**:
  * Trong vòng chưa đầy **0.3 giây**, loa laptop phát ra tiếng chuông **"BÍP"** giòn giã.
  * Màn hình Kiosk nháy sáng xanh, hiển thị banner: **`XÁC THỰC THÀNH CÔNG`**.
  * Cột thông tin bên phải hiện avatar, Họ tên sinh viên, Mã SV, Lớp tín chỉ và trạng thái `✓ CÓ MẶT THÀNH CÔNG`.
  * Bảng danh sách điểm danh thời gian thực nhảy thêm một dòng mới.

### Bước 2: Thử tấn công giả mạo bằng điện thoại (Ghi điểm tuyệt đối về bảo mật)
* **Thao tác**: Lấy điện thoại mở ảnh chân dung rõ nét của sinh viên vừa điểm danh, giơ thẳng trước camera.
* **Hiện tượng xảy ra**:
  * Loa laptop **hoàn toàn im lặng** (không phát tiếng chuông).
  * Thanh hướng dẫn Kiosk chuyển sang cảnh báo màu cam/đỏ:  
    `Trạng thái: Phát hiện nghi vấn giả mạo (Anti-Spoof từ chối) • Điểm tin cậy: 0.1%`.
  * Hệ thống từ chối ghi nhận điểm danh, danh sách sĩ số không bị tăng ảo.
* **Lời bình khi thuyết trình**:  
  *"Thưa Thầy/Cô, mô hình MiniFASNetV2 đã phát hiện vân ma trận màn hình điện thoại và phản xạ gương phẳng, điểm số thực tế tụt về 0.1%, hệ thống chủ động chặn đứng hành vi điểm danh hộ."*

### Bước 3: Quét lại mặt thật lần thứ hai (Chứng minh kiểm soát dữ liệu & độ ổn định)
* **Thao tác**: Cất điện thoại, sinh viên bước vào quét lại mặt thật của mình.
* **Hiện tượng xảy ra**:
  * Loa laptop tiếp tục phát tiếng **"BÍP"** xác nhận.
  * Màn hình Kiosk chuyển sang thẻ màu xanh dương: **`✓ ĐÃ ĐIỂM DANH TRƯỚC ĐÓ (CÓ MẶT)`**.
  * Bảng cơ sở dữ liệu không bị thêm dòng rác, chứng minh tính toàn vẹn dữ liệu (mỗi sinh viên chỉ có 1 bản ghi có mặt trong một buổi học).

---

## 4. Các điểm sáng tạo giải quyết bài toán thực tế

1. **Độc lập hạ tầng mạng**: Nhờ cơ chế ESP32-CAM phát SoftAP cục bộ, hệ thống có thể đem đến bất kỳ phòng học nào, cắm nguồn sạc dự phòng là hoạt động ngay, không bị ảnh hưởng bởi tường lửa hoặc Wi-Fi trường chập chờn.
2. **Khắc phục thiếu thốn phần cứng (Virtual HMI)**: Không cần hàn thêm còi chip buzzer và đèn LED tốn pin và nóng chip trên ESP32, hệ thống điều khiển trực tiếp hệ thống âm thanh của máy tính laptop và hiệu ứng thị giác trên web.
3. **Khởi động 1 chạm (1-Click Desktop)**: Tích hợp sẵn launcher trên màn hình Desktop, bấm đúp chuột là tự động khởi chạy đồng thời Backend, Frontend và Camera Bridge trong 2 giây.
