# Hướng dẫn Nhập và Xuất Dữ liệu

Tài liệu này quy định cấu trúc tệp dữ liệu, quy tắc chuyển đổi ngày giờ, cơ chế giải quyết xung đột và danh mục API phục vụ nhập/xuất danh sách sinh viên cùng lịch học trong hệ thống BTL-IoT.

## 1. Giới hạn Hệ thống

Mọi thao tác nhập tệp qua giao diện web hoặc API trực tiếp đều chịu các ngưỡng kiểm soát tài nguyên sau:

| Thông số | Ngưỡng giới hạn | Hành vi khi vượt ngưỡng |
| :--- | :--- | :--- |
| Dung lượng tệp tải lên | 2 MiB (2.097.152 bytes) | Máy chủ trả mã lỗi HTTP 413 (`Tệp vượt quá kích thước tối đa 2 MiB`). |
| Số dòng danh sách sinh viên | 2.000 dòng dữ liệu | Máy chủ trả mã lỗi HTTP 422 (`Tệp vượt quá giới hạn 2000 dòng`). |
| Số dòng lịch học (CSV / XLSX) | 1.000 dòng dữ liệu | Máy chủ trả mã lỗi HTTP 422 (`Tệp vượt quá giới hạn 1000 dòng`). |
| Số sự kiện lịch học (ICS) | 1.000 sự kiện VEVENT | Máy chủ trả mã lỗi HTTP 422 (`Tệp vượt quá giới hạn 1000 sự kiện`). |
| Định dạng tệp sinh viên | `.csv`, `.xlsx`, `.json` | Máy chủ trả mã lỗi HTTP 415 nếu phần mở rộng không hợp lệ. |
| Định dạng tệp lịch học | `.csv`, `.xlsx`, `.ics` | Máy chủ trả mã lỗi HTTP 415 nếu phần mở rộng không hợp lệ. |

Hệ thống tự động loại bỏ các dòng hoàn toàn rỗng trước khi xử lý logic nghiệp vụ.

## 2. Nhập và Xuất Danh sách Sinh viên

Hệ thống chấp nhận tệp nguồn dưới dạng bảng phẳng (CSV, Excel) hoặc tài liệu cấu trúc (JSON).

### 2.1. Cấu trúc Cột và Nhận diện Tiêu đề

Các cột trong tệp CSV và Excel không phân biệt chữ hoa hay chữ thường, đồng thời tự động loại bỏ dấu tiếng Việt và ký tự đặc biệt khi khớp trường:

| Trường nghiệp vụ | Tiêu đề cột chấp nhận | Bắt buộc | Định dạng và Ràng buộc | Ví dụ mẫu |
| :--- | :--- | :--- | :--- | :--- |
| `student_code` | `ma_sv`, `mssv`, `ma_sinh_vien`, `student_code`, `id` | Có | Chuỗi từ 1 đến 32 ký tự, chỉ gồm chữ in hoa, chữ số, gạch dưới và gạch ngang (biểu thức chính quy: `^[A-Z0-9_-]{1,32}$`). | `B23DCAT901` |
| `name` | `ho_va_ten`, `ho_ten`, `ten`, `name`, `full_name` | Có | Chuỗi từ 1 đến 255 ký tự, không chứa ký tự điều khiển. | `Trần Bảo An` |
| `date_of_birth` | `ngay_sinh`, `dob`, `date_of_birth` | Không | Ngày sinh định dạng `dd/mm/yyyy`, `d/m/yyyy`, `yyyy-mm-dd` hoặc `dd-mm-yyyy`. Năm sinh hợp lệ từ năm 1950 đến năm hiện tại (2026). Chuẩn hóa nội bộ thành `dd/mm/yyyy`. | `15/03/2005` |
| `class_code` | `ma_lop`, `lop`, `class`, `class_code` | Không | Mã lớp hành chính. Nếu lớp chưa tồn tại trong hệ thống, cần truyền tham số `create_missing_classes=true` để tự động tạo mới. | `D23CTAT01-B` |

Đối với tệp JSON, dữ liệu là một mảng danh sách đối tượng chứa các khóa tương ứng (ví dụ: `[{"ma_sv": "B23DCAT901", "name": "Trần Bảo An", "dob": "15/03/2005", "class": "D23CTAT01-B"}]`).

### 2.2. Bảo vệ Dữ liệu Khi Xuất Tệp

Khi xuất danh sách sinh viên qua `GET /api/students/export`:
- Trường nhạy cảm sinh trắc học (`embedding` khuôn mặt trong bảng `FaceReference`) tuyệt đối không bao giờ được đưa vào tệp xuất.
- Ký tự khởi đầu nguy hiểm: Các ô văn bản bắt đầu bằng dấu `=`, `+`, `-`, `@` hoặc ký tự điều khiển tab/xuống dòng sẽ tự động được thêm tiền tố dấu nháy đơn (`'`) để ngăn chặn tấn công Formula Injection (CSV/Excel Macro Injection).
- Tệp CSV xuất ra luôn được gắn ký tự UTF-8 BOM (`\xef\xbb\xbf`) nhằm đảm bảo Microsoft Excel hiển thị đúng tiếng Việt có dấu.

## 3. Nhập và Xuất Lịch Học

Lịch học xác định thời gian diễn ra các buổi học của lớp, phục vụ điểm danh nhận diện khuôn mặt và đồng bộ lịch cá nhân của giảng viên, sinh viên.

### 3.1. Cấu trúc Cột Lịch Học (CSV / XLSX)

| Trường nghiệp vụ | Tiêu đề cột chấp nhận | Bắt buộc | Định dạng và Ràng buộc | Ví dụ mẫu |
| :--- | :--- | :--- | :--- | :--- |
| `class_code` | `ma_lop`, `lop`, `class_code` | Có (*) | Mã lớp trong hệ thống. (*) Có thể bỏ trống trong tệp nếu người dùng chọn cụ thể `class_id` trong biểu mẫu tải lên. | `D23CTAT01-B` |
| `title` | `ten_buoi`, `mon_hoc`, `mon`, `tieu_de`, `title` | Có | Tiêu đề môn học hoặc tên buổi, từ 1 đến 255 ký tự. | `IoT và ứng dụng` |
| `date` | `ngay`, `ngay_hoc`, `date` | Có | Ngày diễn ra buổi học. Chấp nhận `dd/mm/yyyy`, `d/m/yyyy`, `yyyy-mm-dd` hoặc `dd-mm-yyyy`. | `10/11/2026` |
| `start_time` | `bat_dau`, `gio_bat_dau`, `tu`, `start` | Có | Giờ bắt đầu học. Chấp nhận định dạng chuẩn 24h hoặc ký hiệu tắt thông dụng tại Việt Nam. | `07:00` hoặc `7h` |
| `end_time` | `ket_thuc`, `gio_ket_thuc`, `den`, `end` | Có | Giờ kết thúc học. Phải sau giờ bắt đầu, tổng thời lượng một buổi không vượt quá 6 giờ (360 phút). | `09:00` hoặc `9h00` |
| `room` | `phong`, `phong_hoc`, `room` | Không | Mã phòng học, tối đa 64 ký tự. | `402-A2` |
| `note` | `ghi_chu`, `note` | Không | Ghi chú nội dung buổi học hoặc thông tin giảng viên. | `Buổi 1` |

### 3.2. Quy tắc Xử lý Ngày Giờ

Hệ thống hoạt động thống nhất theo múi giờ Việt Nam (`Asia/Ho_Chi_Minh`, ICT, UTC+7):
- Giờ người dùng nhập: Được coi là giờ địa phương Việt Nam.
- Lưu trữ cơ sở dữ liệu: Hệ thống chuyển đổi chính xác sang thời gian UTC trước khi lưu vào SQLite. Khi truy vấn hoặc xuất tệp, backend tự động chuyển đổi ngược lại múi giờ UTC+7.
- Bộ phân tích cú pháp thời gian linh hoạt nhận diện các quy cách ghi giờ sau:
  + Dạng hai chấm: `7:00`, `07:30`, `14:00`, `14:00:00`.
  + Dạng chữ cái: `7h`, `7h30`, `07h`, `07h30`, `14H`, `14H00`.
  + Giờ hợp lệ nằm trong khoảng từ `0` đến `23`, phút từ `0` đến `59`.

## 4. Cơ chế Kiểm Tra Trước và Xử lý Xung Đột

Dữ liệu đào tạo và điểm danh có liên kết chặt chẽ với cơ sở dữ liệu nhận diện khuôn mặt và thiết bị phần cứng. Nhập sai tệp có thể gây trùng lặp thời khóa biểu hoặc phá vỡ cấu trúc điểm danh.

### 4.1. Vì sao Cần Bước Kiểm Tra Trước (Preview Mode)?

Hệ thống áp dụng quy trình kiểm tra hai bước bắt buộc:
1. Bước 1: Thẩm định xem trước (`mode=preview`):
   - Backend đọc toàn bộ tệp, thẩm định định dạng từng trường dữ liệu, kiểm tra tính toàn vẹn của mã lớp và đối chiếu với dữ liệu hiện có trong cơ sở dữ liệu.
   - Thao tác này hoàn toàn không ghi đè hay chỉnh sửa bất kỳ bản ghi nào trong cơ sở dữ liệu.
   - Kết quả trả về cho phép giao diện hiển thị danh sách dòng hợp lệ, phân loại dòng thêm mới, dòng cập nhật, dòng bị bỏ qua, cùng bảng chi tiết toàn bộ lỗi (vị trí dòng, cột bị lỗi, nguyên nhân cụ thể).
2. Bước 2: Xác nhận ghi dữ liệu (`mode=commit`):
   - Người dùng xem xét kỹ lưỡng bảng tổng kết ở bước xem trước. Chỉ khi xác nhận không có sai sót nghiêm trọng, lệnh ghi dữ liệu chính thức mới được thực thi trong một transaction an toàn.

### 4.2. Xử lý Trùng Lặp (on_conflict)

Người dùng có thể chỉ định cách ứng xử khi phát hiện bản ghi đã tồn tại trong cơ sở dữ liệu thông qua tham số `on_conflict`:

| Đối tượng | Chế độ `on_conflict=skip` (Mặc định) | Chế độ `on_conflict=update` |
| :--- | :--- | :--- |
| Danh sách sinh viên | Bỏ qua nếu mã sinh viên (`student_code`) đã tồn tại trong hệ thống. Tăng chỉ số `skipped`. | Cập nhật lại họ tên, ngày sinh và lớp học mới cho mã sinh viên tương ứng. Tăng chỉ số `updated`. |
| Lịch học | Bỏ qua nếu cùng một lớp đã có lịch học trùng giờ bắt đầu hoặc giao thoa khung giờ học (`start_at < other.end_at` và `end_at > other.start_at`). Tăng chỉ số `skipped`. | Cập nhật lại tiêu đề môn, phòng học và ghi chú của lịch học trùng giờ bắt đầu. Nếu lịch này đã liên kết với một buổi điểm danh (`session_id`), buổi điểm danh đó phải đang ở trạng thái nháp (`draft`); nếu đã mở điểm danh hoặc đóng điểm danh, hệ thống từ chối cập nhật và báo lỗi HTTP 409 để bảo toàn tính minh bạch của lịch sử điểm danh. |

## 5. Tích hợp iCalendar (.ics)

Định dạng iCalendar (.ics) cho phép liên kết lịch học với các nền tảng lịch phổ biến như Google Calendar, Microsoft Outlook hoặc Apple Calendar.

### 5.1. Xuất Lịch Sang iCalendar

Endpoint `GET /api/schedules/export?format=ics` sinh tệp `.ics` tuân thủ nghiêm ngặt tiêu chuẩn RFC 5545:
- Dòng kết thúc bằng cặp ký tự CRLF (`\r\n`).
- Mỗi dòng có độ dài tối đa 75 byte UTF-8. Các dòng dài hơn được gập dòng hợp lệ (dòng tiếp nối bắt đầu bằng một dấu cách trắng `\x20`).
- Tích hợp khối `VTIMEZONE` định danh `Asia/Ho_Chi_Minh` kèm tham số `DTSTART;TZID=Asia/Ho_Chi_Minh`.

Cách nhập tệp `.ics` vào Google Calendar:
1. Tải tệp lịch từ hệ thống về máy tính cá nhân.
2. Mở trình duyệt và truy cập Google Calendar (`https://calendar.google.com`).
3. Nhấp vào biểu tượng Bánh răng (Cài đặt) ở góc trên bên phải > Chọn **Cài đặt** (Settings).
4. Ở danh mục bên trái, chọn **Nhập và xuất** (Import & export).
5. Nhấp vào ô **Chọn tệp từ máy tính** và chọn tệp `.ics` vừa tải về.
6. Chọn lịch cá nhân muốn thêm các buổi học vào, sau đó nhấn nút **Nhập** (Import). Toàn bộ các buổi học sẽ hiển thị đúng khung giờ tại Việt Nam.

### 5.2. Nhập Lịch Từ iCalendar và Giới hạn Kỹ thuật

Khi nhập tệp `.ics` vào hệ thống qua `POST /api/schedules/import`:
- **Bắt buộc chọn lớp cụ thể (`class_id`)**: Tệp `.ics` tiêu chuẩn từ các ứng dụng lịch bên ngoài chỉ chứa thuộc tính sự kiện chung (`SUMMARY`, `DTSTART`, `DTEND`, `LOCATION`), không mang trường định danh mã lớp trong cơ sở dữ liệu BTL-IoT. Do đó, người dùng bắt buộc phải chọn lớp tiếp nhận trong biểu mẫu tải lên để hệ thống gán chính xác sự kiện cho lớp đó.
- **Không hỗ trợ quy tắc lặp lại (`RRULE`)**: Nếu tệp chứa thuộc tính `RRULE`, hệ thống sẽ từ chối và phát sinh thông báo lỗi: `Sự kiện thứ N lặp lại (RRULE) chưa được hỗ trợ, hãy xuất lịch dạng từng buổi`.
  
Lý do không hỗ trợ `RRULE`:
- Thời khóa biểu giảng dạy thực tế tại trường đại học thường xuyên có tuần nghỉ lễ, kỳ thi giữa kỳ, đợt nghỉ đột xuất hoặc đổi phòng học.
- Kiến trúc dữ liệu hệ thống quản lý từng buổi học độc lập (`ClassSchedule`) nhằm liên kết 1-1 với phiên điểm danh khuôn mặt (`AttendanceSession`).
- Nếu cho phép quy tắc lặp vô hạn hoặc lặp qua `RRULE`, việc nhập tệp từ các ứng dụng bên ngoài sẽ tự động sinh ra hàng trăm "buổi học ma" rơi vào kỳ nghỉ hè hoặc nghỉ Tết, gây sai lệch thống kê điểm danh và làm xáo trộn dữ liệu của thiết bị điểm danh IoT tại cửa lớp.

## 6. Hướng dẫn Tác vụ qua cURL

Chuẩn bị biến môi trường trước khi thực hiện các lệnh:

```bash
export API_URL="http://localhost:8000/api"
export TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

### 6.1. Tác vụ Sinh viên

Tải tệp mẫu nhập sinh viên định dạng CSV:
```bash
curl -s -X GET "$API_URL/students/import-template?format=csv" \
  -H "Authorization: Bearer $TOKEN" \
  -o mau_sinh_vien.csv
```

Tải tệp mẫu nhập sinh viên định dạng Excel:
```bash
curl -s -X GET "$API_URL/students/import-template?format=xlsx" \
  -H "Authorization: Bearer $TOKEN" \
  -o mau_sinh_vien.xlsx
```

Xuất danh sách sinh viên theo lớp ra định dạng Excel:
```bash
curl -s -X GET "$API_URL/students/export?format=xlsx&class_id=1" \
  -H "Authorization: Bearer $TOKEN" \
  -o danh_sach_sinh_vien_lop1.xlsx
```

Xuất toàn bộ sinh viên ra tệp JSON:
```bash
curl -s -X GET "$API_URL/students/export?format=json" \
  -H "Authorization: Bearer $TOKEN" \
  -o danh_sach_sinh_vien.json
```

Kiểm tra trước tệp sinh viên (Preview mode, tự tạo lớp nếu chưa có):
```bash
curl -s -X POST "$API_URL/students/import" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@docs/samples/sinh_vien_mau.csv" \
  -F "mode=preview" \
  -F "on_conflict=skip" \
  -F "create_missing_classes=true"
```

Xác nhận ghi danh sách sinh viên vào cơ sở dữ liệu (Commit mode):
```bash
curl -s -X POST "$API_URL/students/import" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@docs/samples/sinh_vien_mau.csv" \
  -F "mode=commit" \
  -F "on_conflict=skip" \
  -F "create_missing_classes=true"
```

### 6.2. Tác vụ Lịch Học

Tải tệp mẫu lịch học định dạng CSV:
```bash
curl -s -X GET "$API_URL/schedules/import-template?format=csv" \
  -H "Authorization: Bearer $TOKEN" \
  -o mau_lich_hoc.csv
```

Xuất lịch học dạng bảng CSV:
```bash
curl -s -X GET "$API_URL/schedules/export?format=csv&class_id=1" \
  -H "Authorization: Bearer $TOKEN" \
  -o lich_hoc_lop1.csv
```

Xuất lịch học dạng iCalendar (.ics) đồng bộ Google Calendar:
```bash
curl -s -X GET "$API_URL/schedules/export?format=ics&class_id=1" \
  -H "Authorization: Bearer $TOKEN" \
  -o lich_hoc_lop1.ics
```

Kiểm tra trước tệp lịch học CSV (Preview mode):
```bash
curl -s -X POST "$API_URL/schedules/import" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@docs/samples/lich_hoc_mau.csv" \
  -F "mode=preview" \
  -F "on_conflict=skip"
```

Xác nhận ghi lịch học vào cơ sở dữ liệu (Commit mode):
```bash
curl -s -X POST "$API_URL/schedules/import" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@docs/samples/lich_hoc_mau.csv" \
  -F "mode=commit" \
  -F "on_conflict=skip"
```

Kiểm tra trước tệp lịch học dạng iCalendar (.ics, bắt buộc chỉ định class_id):
```bash
curl -s -X POST "$API_URL/schedules/import" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@lich_hoc.ics" \
  -F "class_id=1" \
  -F "mode=preview" \
  -F "on_conflict=skip"
```

Tạo một buổi lịch học mới qua API JSON:
```bash
curl -s -X POST "$API_URL/schedules" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "class_id": 1,
    "title": "IoT và ứng dụng",
    "date": "2026-11-10",
    "start_time": "07:00",
    "end_time": "09:00",
    "room": "402-A2",
    "note": "Buổi học thực hành lab 1"
  }'
```

Khởi tạo phiên điểm danh từ lịch học có sẵn:
```bash
curl -s -X POST "$API_URL/schedules/1/create-session" \
  -H "Authorization: Bearer $TOKEN"
```
