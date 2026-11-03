# Hệ Thống Điểm Danh Sinh Viên Thông Minh AIoT

**Bài tập lớn học phần IOT và ứng dụng (INT14149) – Nhóm lớp tín chỉ: INT14149-20261-CT02 – Nhóm 05 – Lớp: D23CTAT01-B, Học viện Công nghệ Bưu chính Viễn thông (PTIT).**

Hệ thống điểm danh sinh viên tự động theo kiến trúc phân tầng biên - máy chủ (Decoupled Edge-Server Architecture): Thiết bị biên ESP32-CAM thu nhận và nén hình ảnh, Máy chủ FastAPI điều phối mô hình học sâu chống giả mạo **MiniFASNetV2 (ONNX)** kết hợp mạng nơ-ron tích chập **ResNet-34 (128D Embedding)**, giao diện Web Kiosk chuyên nghiệp xây dựng bằng **React + TypeScript + Tailwind CSS** và phản hồi âm thanh còi bíp tức thì qua loa máy tính (Laptop Audio HMI).

> 📄 **Tài liệu thuyết trình trọng điểm:** [BAO_CAO_THUYET_TRINH.md](./BAO_CAO_THUYET_TRINH.md) — Tóm tắt công nghệ sử dụng, giải thích nguyên lý chống giả mạo vật lý và kịch bản demo 3 bước thuyết phục.

---

## 1. Thông Tin Nhóm Nghiên Cứu & Học Phần

* **Học phần:** IOT và ứng dụng (INT14149)
* **Nhóm lớp tín chỉ:** INT14149-20261-CT02
* **Nhóm:** 05
* **Lớp:** D23CTAT01-B
* **Đơn vị:** Học viện Công nghệ Bưu chính Viễn thông (PTIT)
* **Giảng viên hướng dẫn:** TS. Lê Văn Vịnh
* **Thành viên thực hiện:**
  1. Đỗ Trung Kiên – Mã SV: `B23DCAT156`
  2. Nguyễn Đăng Khoa – Mã SV: `B23DCAT153`
  3. Hoàng Hoàng Tuấn – Mã SV: `B23DCAT320`

---

## 2. Kiến Trúc Hệ Thống Phân Tầng Decoupled (Edge - Backend - Frontend)

```text
┌────────────────────────────────────────────────────────────────────────┐
│ TẦNG 1: THIẾT BỊ THU NHẬN HÌNH ẢNH (EDGE SENSING LAYER)                │
│ Module ESP32-CAM + Cảm biến OV2640 (Độ phân giải CIF 400x296)          │
│ Chế độ Wi-Fi SoftAP (SSID: ESP32_DIEM_DANH - IP: 192.168.4.1)          │
│ (Hoặc Webcam Laptop cục bộ qua chế độ chuyển đổi nhanh)                │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ HTTP MJPEG / JPEG Multipart
┌───────────────────────────────────▼────────────────────────────────────┐
│ TẦNG 2: MÁY CHỦ DỊCH VỤ TRUNG TÂM (FASTAPI BACKEND SERVICE)            │
│ 1. Bộ lọc chất lượng & ROI không gian (Sharpness LapVar, ROI 0.15-0.85)│
│ 2. Khối ổn định chuỗi khung hình (Multi-frame Stability Tracking)      │
│ 3. Mô hình học sâu Anti-Spoofing: MiniFASNetV2 (ONNX CPU Runtime)      │
│ 4. Mạng nơ-ron nhận diện khuôn mặt ResNet-34 trích xuất vector 128D    │
│ 5. Cơ sở dữ liệu SQLite: Quản lý lớp, sinh viên, phiên học, logs      │
│ 6. Phản hồi âm thanh loa máy tính: Synthetic Beep 1800Hz / Sound Wave  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ REST API + Realtime WebSocket
┌───────────────────────────────────▼────────────────────────────────────┐
│ TẦNG 3: GIAO DIỆN NGƯỜI DÙNG KIOSK & ADMIN (REACT + TS + VITE)         │
│ 1. Chế độ Kiosk Toàn màn hình (Kiosk HUD View): Khung ngắm laser,      │
│    thẻ sinh viên trượt vào mượt mà kèm âm thanh Web Audio API          │
│ 2. Bảng điều khiển Quản trị: Quản lý sinh viên, mở/đóng buổi học,     │
│    cấu hình tọa độ ROI trực quan, điểm danh thủ công, xuất file CSV    │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Các Tính Năng Nổi Bật Được Cải Tổ Toàn Diện

1. **Kiến trúc phân tầng Decoupled (FastAPI + React 18 / Vite)**:
   * Backend viết bằng FastAPI module hóa rõ ràng (`api`, `services`, `models`, `schemas`, `database`), có tài liệu Swagger UI tự động tại `/docs`.
   * Giao diện React 18 + TypeScript + Vite + Tailwind CSS với hai chế độ: Kiosk toàn màn hình cho sinh viên và Dashboard quản trị cho giảng viên.
2. **Bộ phát hiện khuôn mặt kép (YuNet + Haar Fallback)**:
   * Sử dụng mạng học sâu YuNet (OpenCV Zoo) làm bộ dò chính với độ chính xác cao và khả năng định vị 5 điểm mốc (landmarks), tự động chuyển sang Haar Cascade khi ảnh thiếu sáng hoặc góc nghiêng khó.
3. **Chống giả mạo Face Anti-Spoofing (MiniFASNetV2 ONNX)**:
   * Tiền xử lý tensor `(1, 3, 80, 80)` chuẩn Minivision, dịch chuyển vùng cắt (box shift) vào trong biên ảnh thay vì cắt cụt để bảo toàn tỷ lệ khuôn mặt. Nhận diện ảnh in và màn hình qua phân tích kết cấu vi mô với ngưỡng pass `0.45`.
4. **Active Liveness phát hiện chớp mắt thời gian thực (EAR Blink Gate)**:
   * Thuật toán Eye Aspect Ratio (EAR) dựa trên dlib 68 landmarks phân tích trực tiếp trên luồng preview 10 Hz. Tự thích ứng ngưỡng nhắm mắt theo đường cơ sở trung vị lịch sử, tiêu thụ dấu vết chớp mắt ngay khi điểm danh thành công để chống dùng lại.
5. **Nhận diện khuôn mặt dlib ResNet-34 đa mẫu (128D Raw Vectors)**:
   * Hỗ trợ đăng ký từ 1 đến 5 ảnh chân dung. Lưu trữ vector 128 chiều dạng thô nguyên bản (không chuẩn hóa L2 sớm) và so khớp khoảng cách Euclid đa mẫu vector hóa với ngưỡng `0.52` và khoảng cách an toàn `0.05`.
6. **Đồng bộ Video & Metadata Canvas mượt mà**:
   * Luồng WebSocket (`/ws/devices/{id}/camera`) phát metadata JSON và khung hình JPEG nhị phân theo nhịp ACK `"next"`. Trình duyệt vẽ khung bounding box trực tiếp trên Canvas HTML5 theo tỷ lệ contain chuẩn, không vẽ đè lên ảnh ở máy chủ.
7. **Điều khiển Cầu nối Camera từ Web & Chống SSRF**:
   * Quản lý tiến trình nền `camera_bridge.py` trực tiếp từ giao diện bảng điều khiển, hỗ trợ chuyển đổi nhanh giữa Webcam laptop và ESP32-CAM. Hàm kiểm thực URL chỉ cho phép kết nối tới IP private LAN hoặc loopback, chặn đứng nguy cơ tấn công SSRF vào mạng nội bộ.
8. **Phản hồi âm thanh còi bíp HMI**:
   * Tự động phát âm báo còi bíp tần số 1800Hz qua loa máy tính (`audio_service.py`) kết hợp Web Audio API trên trình duyệt ngay khi sinh viên điểm danh thành công.

---

## 4. Cấu Trúc Thư Mục Dự Án

```
IOT/
├── backend/                     # FastAPI Backend Server
│   ├── app/
│   │   ├── api/                 # REST API Routers (attendance, auth, devices, students, sessions)
│   │   ├── core/                # Cấu hình, bảo mật token, logic domain
│   │   ├── models/              # Định nghĩa bảng SQLAlchemy (Student, Attendance, Device,...)
│   │   ├── schemas/             # Pydantic schemas kiểm thực dữ liệu
│   │   ├── services/            # Khối xử lý AI (MiniFASNetV2, ResNet, Audio, Detector)
│   │   ├── database.py          # Kết nối CSDL SQLite
│   │   └── main.py              # Khởi tạo ứng dụng FastAPI và tích hợp Frontend tĩnh
│   ├── camera_bridge.py         # Cầu nối truyền ảnh độ trễ thấp từ ESP32-CAM hoặc Webcam
│   ├── seed.py                  # Kịch bản nạp danh sách lớp và vector khuôn mặt tự động
│   └── tests/                   # 41 bài kiểm thử tự động (Unit Tests)
├── frontend/                    # Giao diện Web Kiosk & Quản trị
│   ├── src/
│   │   ├── App.tsx              # Điều phối giao diện, xác thực và quản lý tab
│   │   ├── KioskView.tsx        # Chế độ Kiosk Điểm Danh HUD toàn màn hình
│   │   ├── CameraPanel.tsx      # Bảng điều khiển camera và stream WebSocket
│   │   └── styles.css           # Giao diện Modern Dark HUD & Glassmorphism
│   ├── dist/                    # Bản build production tối ưu (FastAPI phục vụ trực tiếp)
│   └── package.json
├── data/
│   ├── attendance.db            # CSDL SQLite lưu trữ sinh viên, phiên học, lịch sử điểm danh
│   ├── class_roster.json        # Danh sách chính thức 36 sinh viên lớp D23CTAT01-B
│   └── faces/                   # Ảnh chân dung thực tế của các thành viên nhóm
├── models/
│   └── minifasnet-v2/           # Trọng số mô hình học sâu MiniFASNetV2.onnx
├── firmware/
│   ├── esp32_cam/               # Firmware ESP32-CAM chế độ trạm Station
│   └── esp32_cam_softap/        # Firmware ESP32-CAM chế độ điểm phát sóng Access Point
├── Bao_Cao/                     # Báo cáo Word (.docx) và PDF (.pdf) chuẩn biểu mẫu PTIT
├── start.sh                     # Kịch bản khởi động hệ thống 1-click
├── start_esp32.sh               # Kịch bản kết nối Camera ESP32-CAM
└── start_webcam.sh              # Kịch bản kết nối Webcam Laptop cục bộ
```

---

## 5. Hướng Dẫn Cài Đặt & Khởi Chạy

### Cách 1: Khởi chạy 1-Click nhanh nhất (Khuyên dùng)

1. **Bước 1: Chuẩn bị môi trường & file cấu hình `.env`**
   Cài đặt thư viện phụ thuộc:
   ```bash
   pip install fastapi uvicorn sqlalchemy pydantic opencv-python onnxruntime face_recognition Pillow python-dotenv python-multipart
   ```
   Tạo file `.env` từ mẫu:
   ```bash
   cp backend/.env.example .env
   ```
   Mở `.env` và thiết lập `ADMIN_PASSWORD`, `DEVICE_TOKEN`, và `SECRET_KEY` (chuỗi ngẫu nhiên tối thiểu 32 ký tự).

2. **Bước 2: Chạy hệ thống 1-click**
   ```bash
   ./start.sh
   ```
   *Hệ thống sẽ tự động kiểm tra CSDL, nạp danh sách 36 sinh viên, trích xuất vector khuôn mặt và mở máy chủ tại: `http://localhost:8000`.*

3. **Bước 3: Mở trình duyệt và đăng nhập**
   * Truy cập: **`http://localhost:8000`**
   * Tài khoản quản trị: **`admin`** / Mật khẩu: mật khẩu đã đặt trong `.env` (mặc định `admin123456`)
   * Giao diện sẽ tự động mở tab **Kiosk Điểm Danh**.

4. **Bước 4: Kết nối luồng Camera**
   * **Bật/tắt camera trực tiếp từ Web UI (Khuyên dùng)**:
     - Không cần mở terminal thứ hai: vào tab **Thiết bị & vùng điểm danh** trên dashboard, nhấn nút **Bật camera laptop** hoặc **Bật ESP32-CAM** (nhập URL snapshot cổng 80).
     - Backend tự động quản lý tiến trình nền an toàn qua `BridgeControl` (chống SSRF, tự ngắt khi tắt server) và hiển thị trực tiếp PID cùng nhật ký lỗi gần nhất.
   * **Hoặc chạy bằng terminal/kịch bản shell riêng**:
     - *Dùng Webcam máy tính để test nhanh*:
       ```bash
       ./start_webcam.sh
       ```
     - *Dùng phần cứng ESP32-CAM qua Wi-Fi*:
       Kết nối máy tính vào Wi-Fi `ESP32_DIEM_DANH` (mật khẩu: `12345678`), rồi chạy `./start_esp32.sh`.

---

### Cách 2: Chạy bằng Docker Compose

```bash
docker compose up --build -d
```
* Bảng điều khiển Web: `http://localhost:8080`
* API Backend: `http://localhost:8000`

---

## 6. Lưu Ý Khi Nâng Cấp Từ Bản Cũ

1. **Phải đăng ký lại khuôn mặt sinh viên:**
   Bản cũ lưu trữ vector đã bị chuẩn hóa sớm theo chuẩn L2 (độ dài vector = 1.0). Thuật toán mới so khớp đa mẫu trên vector thô 128D nguyên bản của dlib để bảo toàn độ chính xác không gian đặc trưng. Dữ liệu cũ vẫn nạp được nhưng sẽ kích hoạt cảnh báo log và có thể gây sai lệch ngưỡng nhận diện.
2. **Thiết lập `SECRET_KEY` cố định trong file `.env`:**
   Nếu biến này bị bỏ trống, máy chủ sẽ tự sinh ngẫu nhiên một khóa tạm thời trong RAM. Điều này khiến toàn bộ JWT token của giảng viên bị vô hiệu hóa mỗi khi máy chủ khởi động lại.
3. **Nạp lại firmware cho bo mạch ESP32-CAM:**
   Firmware mới tách cổng độc lập theo chuẩn CameraWebServer: cổng 80 phục vụ cấu hình `/status` và chụp ảnh `/capture`, cổng 81 phục vụ stream MJPEG `/stream`. Cần nạp lại mã nguồn trong thư mục `firmware/esp32_cam_softap/`.
4. **Tùy chọn `LIVENESS_MODE=off` khi demo hoặc kiểm thử:**
   Thuật toán phát hiện chớp mắt (EAR) yêu cầu luồng preview ổn định đạt tối thiểu 10–15 FPS. Nếu camera ESP32 bị đặt ở góc nghiêng, khoảng cách xa hoặc đường truyền mạng Wi-Fi bị nghẽn làm tụt khung hình, người vận hành có thể tạm thời tắt cổng chớp mắt bằng cách đặt `LIVENESS_MODE=off` trong `.env`.

---

## 7. Giới Hạn Đã Biết

1. **Không chống được Deepfake và Video Replay chất lượng cao:**
   Cơ chế active liveness qua cử động mí mắt (EAR) chỉ ngăn chặn hiệu quả ảnh in và ảnh tĩnh. Nếu kẻ tấn công phát video quay sẵn người thật đang chớp mắt trên màn hình chất lượng cao, việc ngăn chặn phụ thuộc hoàn toàn vào mô hình PAD MiniFASNet.
2. **Chưa đo lường FAR/FRR trên tập dữ liệu lớn:**
   Hệ thống chưa được thử nghiệm đo tỷ lệ nhận diện sai (FAR) và từ chối sai (FRR) trên tập dữ liệu hàng nghìn sinh viên ngoài thực địa.
3. **Chưa thử nghiệm trực tiếp trên phần cứng thật sau nâng cấp:**
   Toàn bộ pipeline AI và cầu nối sau đợt cải tổ mới được kiểm chứng qua bộ 97 bài kiểm thử tự động và kịch bản E2E trên tập ảnh mẫu công khai trong mạng nội bộ, chưa đo kiểm sóng Wi-Fi thực tế của chip ESP32-CAM.

---

## 8. Kiểm Thử Hệ Thống (Automated Tests)

Dự án duy trì bộ **97 bài kiểm thử tự động** (Pytest) bao phủ toàn diện từ phân quyền token, vòng đời tiến trình bridge, phát hiện chớp mắt EAR, chống giả mạo PAD đến đồng bộ WebSocket:

```bash
PYTHONPATH=backend pytest backend/tests -q
```
*Kết quả đo nghiệm: 97 passed, 3 warnings (các warnings là DeprecationWarning xuất phát từ thư viện bên thứ ba trên môi trường Python 3.14, mã nguồn ứng dụng đạt chuẩn 100%).*
