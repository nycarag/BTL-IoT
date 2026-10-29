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

1. **Phân tách hoàn toàn Frontend & Backend (Decoupled Client-Server)**:
   * Loại bỏ kiến trúc Monolithic script cũ.
   * Backend viết bằng **FastAPI** chia module rõ ràng (`api`, `services`, `models`, `schemas`, `database`), có tài liệu Swagger UI tự động tại `/docs`.
   * Frontend viết bằng **React 18 + TypeScript + Vite + Tailwind CSS**, hỗ trợ cả chế độ Kiosk toàn màn hình cho sinh viên và Admin Dashboard cho giảng viên.
2. **Face Anti-Spoofing bằng Deep Learning (MiniFASNetV2 ONNX)**:
   * Sử dụng mô hình mạng nơ-ron tích chập chuyên dụng phân tích kết cấu vi mô (micro-texture) của khuôn mặt, ngăn chặn hiệu quả tấn công bằng ảnh in (Print Attack) và màn hình điện thoại (Replay Attack).
3. **Phản hồi âm thanh tức thì từ Loa máy tính (Audio HMI)**:
   * Do phần cứng chưa lắp còi chíp vật lý, hệ thống kích hoạt cơ chế phát âm thanh còi bíp tần số 1800Hz qua loa máy tính (`backend/app/services/audio_service.py`) kết hợp bộ tổng hợp âm thanh Web Audio API trên trình duyệt.
4. **Cơ sở dữ liệu khuôn mặt thực tế đã nạp sẵn**:
   * Tích hợp toàn bộ hồ sơ 36 sinh viên lớp D23CTAT01-B và vector embedding 128 chiều của các thành viên nhóm vào CSDL SQLite.
5. **Hỗ trợ kết nối Camera linh hoạt**:
   * Hỗ trợ luồng stream từ bo mạch **ESP32-CAM** qua Wi-Fi.
   * Hỗ trợ cờ `--webcam` để chạy thử nghiệm trực tiếp bằng **Webcam Laptop** mà không cần cắm bo mạch ESP32.

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

1. **Bước 1: Cài đặt thư viện phụ thuộc (nếu chưa có)**
   ```bash
   pip install fastapi uvicorn sqlalchemy pydantic opencv-python onnxruntime face_recognition Pillow python-dotenv python-multipart
   ```

2. **Bước 2: Chạy hệ thống 1-click**
   ```bash
   ./start.sh
   ```
   *Hệ thống sẽ tự động kiểm tra CSDL, nạp danh sách 36 sinh viên, trích xuất vector khuôn mặt và mở máy chủ tại: `http://localhost:8000`.*

3. **Bước 3: Mở trình duyệt và đăng nhập**
   * Truy cập: **`http://localhost:8000`**
   * Tài khoản quản trị: **`admin`** / Mật khẩu: **`admin123456`**
   * Giao diện sẽ tự động mở tab **🖥️ Kiosk Điểm Danh**.

4. **Bước 4: Kết nối luồng Camera (Mở terminal thứ hai)**
   * **Nếu dùng Webcam máy tính để test nhanh**:
     ```bash
     ./start_webcam.sh
     ```
   * **Nếu dùng phần cứng ESP32-CAM qua Wi-Fi**:
     - Kết nối máy tính vào Wi-Fi do ESP32 phát ra: `ESP32_DIEM_DANH` (mật khẩu: `12345678`).
     - Chạy script kết nối:
       ```bash
       ./start_esp32.sh
       ```

---

### Cách 2: Chạy bằng Docker Compose

```bash
docker compose up --build -d
```
* Bảng điều khiển Web: `http://localhost:8080`
* API Backend: `http://localhost:8000`

---

## 6. Kiểm Thử Hệ Thống (Unit Tests)

Dự án bao gồm bộ 41 bài kiểm thử tự động bao phủ toàn bộ luồng nghiệp vụ API, bộ lọc ROI, phát hiện giả mạo và độ trễ buffer:

```bash
cd backend
python3 -m unittest discover -s tests -v
```
*Kết quả: 41 tests passed 100%.*
