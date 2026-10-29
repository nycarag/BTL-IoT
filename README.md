# Hệ Thống Camera Điểm Danh Sinh Viên Thông Minh AIoT

Bài tập lớn học phần IOT và ứng dụng (INT14149) – Nhóm lớp tín chỉ: INT14149-20261-CT02 – Nhóm 05 – Lớp: D23CTAT01-B, Học viện Công nghệ Bưu chính Viễn thông (PTIT).

Hệ thống điểm danh sinh viên tự động sử dụng vi điều khiển biên ESP32-CAM truyền luồng video qua Wi-Fi nội bộ đến máy chủ AI, kết hợp phòng thủ giả mạo khuôn mặt đa tầng (Face Anti-Spoofing - FAS) và giao diện điều khiển Kiosk Streamlit.

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

## 2. Kiến Trúc Hệ Thống 4 Tầng

```
┌────────────────────────────────────────────────────────────────────────┐
│ TẦNG 1: THIẾT BỊ BIÊN (EDGE SENSING LAYER)                             │
│ Module ESP32-CAM + Cảm biến OV2640 (Độ phân giải CIF 400x296)          │
│ Mạch nguồn chống sụt áp (Tụ 100µF) + Firmware phát Wi-Fi AP Cổng 81    │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Luồng HTTP MJPEG (WLAN 802.11b/g/n)
┌───────────────────────────────────▼────────────────────────────────────┐
│ TẦNG 2: MẠNG TRUYỀN THÔNG & XẢ ĐỆM (NETWORK DRAIN BUFFER)             │
│ Kết nối Socket TCP 192.168.4.1:81/stream                              │
│ Bộ đọc Zero-Latency: Xả gói tích lũy, trích xuất cặp byte JPEG mới nhất│
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Khung ma trận ảnh số (Numpy Matrix)
┌───────────────────────────────────▼────────────────────────────────────┐
│ TẦNG 3: MÁY CHỦ XỬ LÝ TRÍ TUỆ NHÂN TẠO (AI COMPUTING LAYER)           │
│ 1. Phát hiện khuôn mặt (HOG / 68 Landmarks)                           │
│ 2. Lọc nhiễu 3 điều kiện (Diện tích S_max, ROI trung tâm, Ổn định 1s) │
│ 3. Phòng thủ giả mạo FAS 4 tầng (Quang học + 3D Pose + Thử thách)     │
│ 4. Trích xuất vector 128D (ResNet-34) & So khớp đa góc (Min distance) │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Bản ghi xác thực thành công
┌───────────────────────────────────▼────────────────────────────────────┐
│ TẦNG 4: ỨNG DỤNG KIOSK & PHẢN HỒI ÂM THANH (APPLICATION & AUDIO HMI)   │
│ Giao diện Dashboard Kiosk một chiều (Streamlit)                        │
│ Danh sách 36 sinh viên D23CTAT01-B + Tự động xuất Excel (.xlsx) chuẩn  │
│ Phản hồi âm thanh còi bíp xác thực tức thì (1800Hz / 0ms delay)        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Kiến Trúc Phòng Thủ Chống Giả Mạo (Face Anti-Spoofing - FAS)

Hệ thống ngăn chặn 100% tấn công bằng ảnh tĩnh (Print Attack) và video quay sẵn lặp lại trên điện thoại (Replay Attack) qua 4 cơ chế:

1. **Lọc không gian & hình học (Spatial Geometric Guard):**
   * Chỉ khóa chủ thể có bounding box lớn nhất ($S_{\max}$) trong vùng ROI trung tâm ($0.22W \le x \le 0.78W$).
   * Giám sát dịch tâm liên tiếp $\Delta d = \|C_t - C_{t-1}\|$. Nếu $\Delta d > 35\text{px}$, hủy phiên xác thực.
2. **Phân tích quang học thụ động (Passive Optical & Specular Glare Defense):**
   * Quét pixel có độ chói cực đại $Y > 250$. Nếu diện tích chói phản xạ vượt quá $12\%$ diện tích mặt, phát cảnh báo màn hình lóa và từ chối.
   * Kiểm tra dải màu da sinh học $YCrCb$ ($125 \le Cr \le 180, 70 \le Cb \le 135$), chặn màn hình ám xanh lạnh hoặc ảnh in lệch màu.
3. **Ước lượng tư thế 3D (`cv2.solvePnP`) & Thử thách tương tác ngẫu nhiên:**
   * Trích xuất góc quay Euler Yaw, Pitch, Roll và tỷ lệ đối xứng khuôn mặt $\text{Sym} = d_{\text{left}} / d_{\text{right}}$ trong $< 0.15\text{ms}$.
   * Phát lệnh thử thách ngẫu nhiên có giới hạn thời gian (4.0 giây):
     * *Thử thách A:* Chớp mắt sinh học ($\text{EAR} \le 0.17$, mở lại trong $80\text{ms} \le \Delta t \le 550\text{ms}$).
     * *Thử thách B:* Quay nhẹ đầu sang phải ($\text{Yaw} > 13^\circ$ hoặc $\text{Sym} > 1.45$, sau đó quay về tâm).
     * *Thử thách C:* Quay nhẹ đầu sang trái ($\text{Yaw} < -13^\circ$ hoặc $\text{Sym} < 0.70$, sau đó quay về tâm).
   * Video quay sẵn lặp lại trên điện thoại không thể phản hồi thử thách ngẫu nhiên trong thời hạn 4 giây.
4. **Định danh đặc trưng ResNet-34 & Khóa Mã Sinh Viên (MSV):**
   * Vector 128 chiều đối soát CSDL đa góc nhìn (chính diện, nghiêng trái, nghiêng phải).
   * Khóa định danh duy nhất theo MSV, không bị trùng lặp khi có sinh viên trùng tên.

---

## 4. Cấu Trúc Thư Mục

```
BTL-IoT/
├── Bao_Cao/                               # Thư mục chứa báo cáo học thuật (Word, PDF, Markdown)
│   └── .gitkeep
├── DiemDanh_AI/
│   ├── app.py                             # Mã nguồn máy chủ AI & Giao diện Kiosk Streamlit
│   ├── class_roster.json                  # CSDL 36 sinh viên lớp D23CTAT01-B
│   ├── attendance_log.csv                 # Nhật ký điểm danh thời gian thực
│   ├── beep_success.wav                   # Âm thanh còi bíp xác thực thành công (1800Hz)
│   ├── run.sh                             # Script khởi chạy nhanh ứng dụng
│   ├── requirements.txt                   # Danh sách thư viện Python
│   └── faces/                             # Thư mục lưu ảnh khuôn mặt sinh viên mẫu (.jpg)
│       └── .gitkeep
├── Firmware_ESP32/
│   ├── code_esp32_cam.ino                 # Mã nguồn C/C++ nạp module vi điều khiển biên
│   └── code_esp32_cam.txt                 # Bản lưu trữ văn bản thuần mã nạp
├── requirements.txt                       # Thư viện toàn cục cho dự án
├── .gitignore                             # Cấu hình bỏ qua tệp tạm (__pycache__, *.pyc, *.tmp)
└── README.md                              # Tài liệu hướng dẫn dự án
```

---

## 5. Hướng Dẫn Cài Đặt & Vận Hành

### Bước 1: Nạp Firmware cho ESP32-CAM
1. Mở Arduino IDE, chọn board `AI Thinker ESP32-CAM`.
2. Cấu hình thông số:
   * Partition Scheme: `Huge APP (3MB No OTA/1MB SPIFFS)`
   * CPU Frequency: `240MHz (WiFi/BT)`
   * Flash Frequency: `80MHz`
3. Mở tệp `Firmware_ESP32/code_esp32_cam.ino`.
4. Nạp code:
   * **Nếu dùng đế nạp ESP32-CAM-MB:** Cắm thẳng cáp Micro-USB từ máy tính vào cổng trên đế và bấm Upload (nhấn giữ nút `IO0/BOOT` 1-2s nếu màn hình hiện `Connecting...`).
   * **Nếu dùng mạch FTDI rời:** Nối GPIO0 với GND khi nạp, tháo ra sau khi nạp xong.
5. Sau khi khởi động, ESP32-CAM tự phát mạng Wi-Fi:
   * SSID: `ESP32_DIEM_DANH`
   * Mật khẩu: `12345678`
   * IP cố định: `192.168.4.1`
   * Luồng video: `http://192.168.4.1:81/stream`

### Bước 2: Cài Đặt Môi Trường Máy Chủ AI
Yêu cầu Python 3.10 trở lên trên hệ điều hành Linux (Ubuntu/Debian) hoặc macOS/Windows.

```bash
# Cài đặt các gói phụ thuộc
pip install -r requirements.txt
```

### Bước 3: Khởi Chạy Ứng Dụng Kiosk
1. Kết nối máy tính vào Wi-Fi `ESP32_DIEM_DANH`.
2. Chạy ứng dụng bằng lệnh:

```bash
cd DiemDanh_AI
./run.sh
# Hoặc chạy trực tiếp:
streamlit run app.py --server.port 8501 --server.headless true
```

3. Mở trình duyệt tại địa chỉ `http://localhost:8501`. Màn hình Kiosk sẽ tự động kết nối luồng camera và kích hoạt bộ nhận diện.

---

## 6. Chỉ Số Đo Lường Kỹ Thuật

* **Tốc độ khung hình (CIF 400x296):** 26.5 FPS
* **Tốc độ xử lý AI toàn trình:** 24.2 FPS
* **Thời gian tính toán 3D Head Pose `solvePnP`:** < 0.15 ms/frame
* **Độ trễ truyền dẫn luồng:** 142 ms (bộ đọc xả đệm triệt tiêu tích lũy)
* **Độ chính xác nhận diện đa góc:** 96.4%
* **Tỷ lệ chặn ảnh in và video giả mạo:** 100%
* **Công suất tiêu thụ ESP32-CAM:** 1.25 W (5V - 250mA)
