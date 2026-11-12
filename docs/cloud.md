# Tầng Cloud và Đối chiếu Cấp độ IoT

## 1. Giới thiệu tầng cloud
Tầng cloud lưu trữ bản sao dữ liệu điểm danh, quản lý thông tin trạng thái thiết bị và tổng hợp báo cáo chuyên cần. Cloud không nhận ảnh, không nhận vector khuôn mặt 128 chiều. Mọi bước nhận diện AI và chống giả mạo đều chạy tại chỗ trên gateway laptop. Dữ liệu đẩy lên cloud chỉ gồm các trường text và số của bản ghi điểm danh đã xác thực.

## 2. Đối chiếu bảng cấp độ IoT của học phần
Nguồn cấp độ dựa theo tài liệu bài giảng học phần.

| Tiêu chí | Hệ thống này | Bằng chứng mã nguồn |
| :--- | :--- | :--- |
| Nơi lưu trữ | Phân tán: SQLite tại gateway làm gốc, Google Sheets làm bản sao đám mây | `backend/app/database.py`, `backend/app/services/cloud_sync.py`, `cloud/apps_script/Code.gs` |
| Nơi phân tích | Phân tán: AI nhận diện 4 chặng tại gateway, thống kê chuyên cần trên cloud | `backend/app/services/face_pipeline.py`, `cloud/apps_script/Code.gs` |
| Số nút | Nhiều nút camera: ESP32-CAM và điện thoại chạy qua Wi-Fi | `start_phone.sh`, `start_esp32.sh`, `start_webcam.sh`, `backend/camera_bridge.py` |
| Thành phần đặc trưng | Có gateway điều phối xử lý trung gian trong mạng cục bộ | `backend/app/main.py`, `backend/camera_bridge.py` |

Hệ thống khớp các cột của Level 5: lưu trữ trên cloud, phân tích ở cả gateway và cloud, nhiều nút camera, có nút điều phối (gateway) ở mạng cục bộ.

## 3. Sơ đồ kiến trúc ba tầng
```text
+---------------------------------------+
|             NÚT CAMERA                |
|  - ESP32-CAM (Wi-Fi, HTTP MJPEG/JPEG) |
|  - Điện thoại (start_phone.sh)        |
|  - Webcam laptop (dự phòng)           |
+-------------------+-------------------+
                    | Gửi frame video / ảnh chụp (HTTP)
                    v
+-------------------+-------------------+
|         GATEWAY / COORDINATOR         |
|  - camera_bridge.py (nhận diện 4 bước)|
|  - FastAPI (REST API, WebSocket)      |
|  - SQLite (data/attendance.db, bản gốc)|
|  - Tác vụ nền cloud_sync (POST JSON)  |
+-------------------+-------------------+
                    | Đồng bộ bản ghi điểm danh + thiết bị (POST HTTP 302)
                    v
+-------------------+-------------------+
|              CLOUD                    |
|  - Google Apps Script (Code.gs)       |
|  - Google Sheets: DiemDanh, ThietBi,  |
|    ThongKeBuoi, ThongKeSV, Lenh       |
+---------------------------------------+
```

## 4. Hợp đồng dữ liệu gateway và cloud
Gateway gửi dữ liệu định kỳ qua phương thức POST JSON đến Web App Google Apps Script.

### Dữ liệu gửi đi (Gateway -> Cloud)
- `token`: Chuỗi khóa bí mật xác thực giữa gateway và cloud.
- `gateway_id`: Tên định danh của gateway gửi dữ liệu.
- `attendance`: Danh sách bản ghi điểm danh, mỗi phần tử gồm: `event_id` (`<gateway_id>-att-<id>`), `checked_at` (giờ Việt Nam YYYY-MM-DD HH:MM:SS), `student_code`, `student_name`, `class_code`, `session_id`, `session_title`, `status`, `device_id` (chuỗi rỗng nếu vắng/thủ công), `verification`.
- `devices`: Danh sách thiết bị, gồm: `device_id`, `name`, `status` (`online` hoặc `offline`), `last_seen`. Không gửi địa chỉ IP.
- `command_results`: Danh sách kết quả thực thi lệnh (mảng rỗng khi chưa xử lý lệnh).

### Dữ liệu phản hồi (Cloud -> Gateway)
- Thành công: `{"ok": true, "added": <số dòng mới>, "commands": [...]}`
- Thất bại: `{"ok": false, "error": "token|json|<chi tiết>"}`

## 5. Phân tích trên cloud
Apps Script tự động tính toán lại hai bảng thống kê sau mỗi lượt nhận bản ghi điểm danh mới:
- `ThongKeBuoi`: Tổng hợp theo buổi học gồm mã buổi, tên buổi, lớp, số sinh viên có mặt, đi muộn, vắng, tổng số và tỷ lệ chuyên cần theo công thức `(có mặt + đi muộn) / tổng * 100`.
- `ThongKeSV`: Tổng hợp theo sinh viên gồm mã số, họ tên, lớp, số buổi điểm danh, số lần có mặt, đi muộn, vắng. Tự động gắn nhãn cảnh báo `Vắng X buổi` khi sinh viên vắng từ 2 buổi trở lên.

## 6. Cơ chế giữ và gửi bù khi mất mạng
Gateway dùng khóa `cloud_last_attendance_id` trong bảng `app_settings` làm con trỏ đồng bộ. Khi gửi thành công một lô, con trỏ được cập nhật thành ID điểm danh lớn nhất của lô đó.
Nếu mất kết nối mạng hoặc cloud báo lỗi, con trỏ giữ nguyên giá trị cũ. Bản ghi mới tạo vẫn lưu an toàn trong SQLite. Khi mạng hoạt động trở lại, gateway tự động quét từ con trỏ cũ và gửi bù toàn bộ bản ghi tồn đọng. Phía cloud tự đối chiếu trường `event_id` trên sheet `DiemDanh` để loại bỏ các bản ghi trùng lặp.

## 7. Các bước cài đặt
1. Tạo một Google Spreadsheet mới trên Google Drive cá nhân.
2. Mở mục Tiện ích mở rộng (Extensions) > Apps Script, dán toàn bộ nội dung từ `cloud/apps_script/Code.gs`.
3. Thay đổi giá trị biến `TOKEN` ở dòng 5 thành chuỗi ngẫu nhiên bí mật.
4. Chọn Triển khai (Deploy) > Tùy chọn triển khai mới (New deployment) > Loại: Ứng dụng web (Web app). Đặt quyền truy cập cho bất kỳ ai (Anyone) và sao chép URL triển khai.
5. Khai báo 5 biến môi trường tương ứng vào file `.env` tại thư mục gốc backend.
6. Khởi động lại backend để tiến trình đồng bộ nền `cloud_sync` bắt đầu hoạt động.

### Bảng biến môi trường
| Tên biến | Mặc định | Ý nghĩa |
| :--- | :--- | :--- |
| `CLOUD_SYNC_URL` | `""` | URL triển khai Web App dạng `/exec` của Google Apps Script |
| `CLOUD_SYNC_TOKEN` | `""` | Khóa bí mật khớp với biến `TOKEN` trong `Code.gs` |
| `CLOUD_SYNC_INTERVAL_SECONDS` | `15` | Chu kỳ chạy tác vụ đồng bộ nền (từ 5 đến 300 giây) |
| `GATEWAY_ID` | `gateway-laptop-01` | Mã định danh của gateway đính kèm vào mỗi bản ghi |
| `CLOUD_SYNC_BACKFILL` | `false` | Đồng bộ toàn bộ dữ liệu cũ từ ID 0 khi chưa có con trỏ |

## 8. Giới hạn hệ thống
- Google Sheets là bảng tính văn phòng đa dụng, không phải hệ quản trị cơ sở dữ liệu thời gian thực hay nền tảng IoT công nghiệp chuyên biệt.
- Hệ thống dùng chung một chuỗi token bí mật giữa gateway và cloud, chưa phân quyền chi tiết theo từng người dùng.
- Khi giảng viên thay đổi ngưỡng thời gian đi muộn tại gateway, trạng thái các bản ghi cũ trên gateway được tính lại nhưng Google Sheets không cập nhật ngược lại các dòng đã ghi.
- Nhóm hiện có một phần cứng ESP32-CAM nên nút camera thứ hai sử dụng ứng dụng camera IP trên điện thoại qua script `start_phone.sh`, hoặc dùng webcam laptop làm phương án dự phòng.
- Thao tác mất mạng vật lý rồi bật lại trên máy thật và nhận lệnh điều khiển từ cloud chưa được thử nghiệm trên thiết bị thật, mới chỉ được xác thực thông qua bộ kiểm thử tự động.
