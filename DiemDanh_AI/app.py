import streamlit as st
import streamlit.components.v1 as components
import cv2
import numpy as np
import face_recognition
import os
import time
import random
import json
import re
import io
import shutil
import unicodedata
import pandas as pd
from datetime import datetime
import urllib.request
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# ==========================================================
# CẤU HÌNH GIAO DIỆN HỆ THỐNG CHUẨN KIOSK
# ==========================================================
st.set_page_config(
    page_title="Hệ Thống Điểm Danh Sinh Viên - PTIT",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# STYLING: CHỮ TO RÕ RÀNG, KHÔNG DÙNG ICON TRÊN NÚT BẤM, PHÂN CẤP THỊ GIÁC CHUẨN
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif !important;
        color: #0F172A;
    }
    
    .stApp {
        background-color: #F8FAFC !important;
    }
    
    #MainMenu, footer, header {
        visibility: hidden;
    }
    
    /* KHUNG TIÊU ĐỀ CHUẨN THÔNG TIN BÁO CÁO NHÓM 05 */
    .header-bar {
        background: #FFFFFF;
        border: 1px solid #CBD5E1;
        border-radius: 8px;
        padding: 16px 20px;
        margin-bottom: 16px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .header-school {
        font-size: 12px;
        font-weight: 700;
        color: #2563EB;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .header-main-title {
        font-size: 20px;
        font-weight: 800;
        color: #0F172A;
        margin: 2px 0 0 0;
    }
    .header-class-info {
        font-size: 13px;
        color: #475569;
        margin-top: 3px;
    }
    .clock-display {
        font-size: 24px;
        font-weight: 800;
        font-family: monospace;
        color: #0F172A;
        text-align: right;
    }
    .date-display {
        font-size: 13px;
        font-weight: 600;
        color: #64748B;
        text-align: right;
    }
    
    /* Ô THỐNG KÊ SĨ SỐ */
    .stat-container {
        display: flex;
        gap: 12px;
        margin-bottom: 12px;
    }
    .stat-box {
        flex: 1;
        padding: 12px 16px;
        border-radius: 8px;
        text-align: center;
        border: 1px solid #CBD5E1;
    }
    .stat-box-present {
        background: #ECFDF5;
        border-color: #A7F3D0;
    }
    .stat-box-absent {
        background: #F8FAFC;
        border-color: #E2E8F0;
    }
    .stat-number {
        font-size: 24px;
        font-weight: 800;
        line-height: 1.1;
    }
    .stat-tag {
        font-size: 12px;
        font-weight: 700;
        text-transform: uppercase;
        margin-top: 4px;
    }
    
    /* BẢNG DANH SÁCH SINH VIÊN */
    .table-wrapper {
        background: #FFFFFF;
        border: 1px solid #CBD5E1;
        border-radius: 8px;
        overflow: hidden;
        max-height: 480px;
        overflow-y: auto;
    }
    .roster-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 13px;
        text-align: left;
    }
    .roster-table th {
        background: #F1F5F9;
        color: #1E293B;
        font-weight: 700;
        padding: 10px 12px;
        border-bottom: 1px solid #CBD5E1;
        position: sticky;
        top: 0;
        z-index: 2;
    }
    .roster-table td {
        padding: 9px 12px;
        border-bottom: 1px solid #F1F5F9;
        color: #1E293B;
    }
    .roster-table tr:hover {
        background-color: #F8FAFC;
    }
    .row-present {
        background-color: #F0FDF4;
    }
    .status-badge {
        display: inline-block;
        padding: 3px 8px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 700;
    }
    .badge-ok {
        background: #DCFCE7;
        color: #15803D;
        border: 1px solid #86EFAC;
    }
    .badge-pending {
        background: #F1F5F9;
        color: #64748B;
        border: 1px solid #CBD5E1;
    }
    
    /* THÔNG BÁO DƯỚI KHUNG CAMERA - CHỮ TO RÕ */
    .message-banner {
        padding: 14px 18px;
        border-radius: 6px;
        font-size: 15px;
        font-weight: 700;
        margin-bottom: 12px;
        border: 1px solid #CBD5E1;
        text-align: center;
    }
    .msg-idle {
        background: #FFFFFF;
        color: #334155;
        border-color: #CBD5E1;
    }
    .msg-process {
        background: #EFF6FF;
        color: #1D4ED8;
        border-color: #BFDBFE;
    }
    .msg-action {
        background: #FFFBEB;
        color: #B45309;
        border-color: #FDE68A;
    }
    .msg-success {
        background: #ECFDF5;
        color: #047857;
        border-color: #A7F3D0;
    }
    
    /* NÚT BẤM TO RÕ RÀNG, KHÔNG DÙNG ICON */
    .stButton>button, .stDownloadButton>button {
        width: 100% !important;
        border-radius: 8px !important;
        font-weight: 700 !important;
        font-size: 15px !important;
        padding: 12px 20px !important;
        letter-spacing: 0.02em !important;
        border: 1px solid #CBD5E1 !important;
        background: #FFFFFF !important;
        color: #0F172A !important;
        transition: all 0.15s ease !important;
    }
    .stButton>button:hover, .stDownloadButton>button:hover {
        background: #F1F5F9 !important;
        border-color: #94A3B8 !important;
    }
    
    /* KHUNG CAMERA */
    div[data-testid="stImage"] img {
        border-radius: 8px !important;
        border: 1px solid #CBD5E1 !important;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================================
# CÁC HÀM XỬ LÝ DỮ LIỆU VÀ CHUẨN HÓA TIẾNG VIỆT
# ==========================================================
def remove_accents(input_str):
    if not input_str:
        return ""
    s1 = unicodedata.normalize('NFD', str(input_str))
    s2 = ''.join(c for c in s1 if unicodedata.category(c) != 'Mn')
    return s2.replace('đ', 'd').replace('Đ', 'D').lower().strip()

ROSTER_FILE = os.path.join(os.path.dirname(__file__), "class_roster.json")
LOG_FILE = os.path.join(os.path.dirname(__file__), "attendance_log.csv")
BEEP_SOUND_FILE = os.path.join(os.path.dirname(__file__), "beep_success.wav")

def play_attendance_beep():
    """Phát tiếng BÍP qua loa máy tính khi điểm danh thành công (chạy nền, không chặn stream AI)"""
    def _worker():
        if os.path.exists(BEEP_SOUND_FILE):
            ret = os.system(f"paplay '{BEEP_SOUND_FILE}' >/dev/null 2>&1 || aplay '{BEEP_SOUND_FILE}' >/dev/null 2>&1")
            if ret == 0:
                return
        os.system("paplay /usr/share/sounds/freedesktop/stereo/complete.oga >/dev/null 2>&1 &")
    threading.Thread(target=_worker, daemon=True).start()

def load_class_roster():
    if os.path.exists(ROSTER_FILE):
        try:
            with open(ROSTER_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def load_attendance_records():
    records = {}
    if os.path.exists(LOG_FILE):
        try:
            df = pd.read_csv(LOG_FILE)
            for _, row in df.iterrows():
                name = str(row.get("Họ và Tên", "")).strip()
                sid = str(row.get("Mã SV", "")).strip()
                t = str(row.get("Thời gian", "")).strip()
                # Khóa chính định danh duy nhất là Mã Sinh Viên (sid)
                if sid and sid != "nan":
                    records[sid] = {"time": t, "id": sid, "name": name}
        except Exception:
            pass
    return records

if not os.path.exists(LOG_FILE):
    pd.DataFrame(columns=["Thời gian", "Mã SV", "Họ và Tên", "Trạng thái", "Xác thực"]).to_csv(LOG_FILE, index=False)

def is_student_present(student, attendance_records):
    sid = student.get("id", "")
    # Chỉ xác nhận có mặt khi Mã SV trùng khớp chính xác (tránh nhầm khi trùng họ tên trong lớp)
    if sid and sid in attendance_records:
        return True, attendance_records[sid].get("time", "-")
    return False, "-"

# ==========================================================
# HÀM XUẤT FILE EXCEL CHUẨN THÔNG TIN BÁO CÁO NHÓM
# ==========================================================
def create_excel_report(roster, attendance_records):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Diem Danh D23CTAT01-B"
    
    ws.merge_cells('A1:G1')
    ws['A1'] = "HỌC VIỆN CÔNG NGHỆ BƯU CHÍNH VIỄN THÔNG - KHOA AN TOÀN THÔNG TIN"
    ws['A1'].font = Font(name="Arial", size=11, bold=True, color="475569")
    ws['A1'].alignment = Alignment(horizontal="center", vertical="center")
    
    ws.merge_cells('A2:G2')
    ws['A2'] = "BẢNG ĐIỂM DANH SINH VIÊN - HỌC PHẦN: IOT VÀ ỨNG DỤNG (INT14149)"
    ws['A2'].font = Font(name="Arial", size=14, bold=True, color="1E3A8A")
    ws['A2'].alignment = Alignment(horizontal="center", vertical="center")
    
    ws.merge_cells('A3:G3')
    ws['A3'] = f"Nhóm lớp: INT14149-20261-CT02  |  Lớp: D23CTAT01-B (Nhóm 05)  |  HK1 (2026 - 2027)  |  GVHD: TS. Lê Văn Vịnh  |  Ngày xuất: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    ws['A3'].font = Font(name="Arial", size=10, italic=True, color="475569")
    ws['A3'].alignment = Alignment(horizontal="center", vertical="center")
    
    ws.append([]) # Dòng 4
    
    headers = ["STT", "Mã Sinh Viên", "Họ và Tên", "Ngày Sinh", "Lớp", "Trạng Thái", "Thời Gian Điểm Danh"]
    ws.append(headers) # Dòng 5
    
    header_fill = PatternFill(start_color="1E40AF", end_color="1E40AF", fill_type="solid")
    header_font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
    thin_border = Border(
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1')
    )
    
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=5, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border
        
    row_num = 6
    for idx, student in enumerate(roster, start=1):
        sid = student["id"]
        sname = student["name"]
        sdob = student["dob"]
        sclass = student["class"]
        
        is_p, att_time = is_student_present(student, attendance_records)
        status_text = "Có mặt" if is_p else "Chưa điểm danh"
        
        ws.append([idx, sid, sname, sdob, sclass, status_text, att_time])
        
        status_cell = ws.cell(row=row_num, column=6)
        if is_p:
            status_cell.font = Font(name="Arial", size=11, bold=True, color="047857")
            status_cell.fill = PatternFill(start_color="D1FAE5", end_color="D1FAE5", fill_type="solid")
        else:
            status_cell.font = Font(name="Arial", size=11, color="64748B")
            status_cell.fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
            
        for c in range(1, 8):
            ws.cell(row=row_num, column=c).border = thin_border
            if c in [1, 2, 4, 5, 6, 7]:
                ws.cell(row=row_num, column=c).alignment = Alignment(horizontal="center")
        row_num += 1

    for col in ws.columns:
        max_len = max(len(str(c.value or '')) for c in col)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 12)
        
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()

import threading

# ==========================================================
# BỘ ĐỌC CAMERA ĐA LUỒNG ZERO-LATENCY (TRIỆT TIÊU TOÀN BỘ ĐỘ TRỄ)
# ==========================================================
class CameraReader:
    def __init__(self, source):
        self.source = source
        self.is_http = str(source).startswith("http://") or str(source).startswith("https://")
        self.lock = threading.Lock()
        self.latest_frame = None
        self.running = False
        self.thread = None
        self.ready = False
        self.cap = None

        if not self.is_http:
            dev_idx = int(source) if str(source).isdigit() else source
            self.cap = cv2.VideoCapture(dev_idx)
            self.ready = self.cap.isOpened()
            self.stream = None
        else:
            self.cap = None
            self.stream = None
            try:
                req = urllib.request.Request(self.source, headers={'User-Agent': 'Mozilla/5.0'})
                # Mở kết nối HTTP stream duy nhất, không tạo connection thừa gây nghẽn socket ESP32
                self.stream = urllib.request.urlopen(req, timeout=2.5)
                self.ready = True
            except Exception:
                self.ready = False

        if self.ready:
            self.running = True
            self.thread = threading.Thread(target=self._worker_loop, daemon=True)
            self.thread.start()
            st_time = time.time()
            while time.time() - st_time < 2.0 and self.latest_frame is None:
                time.sleep(0.04)

    def _worker_loop(self):
        if not self.is_http:
            while self.running:
                if self.cap is not None and self.cap.isOpened():
                    ret, frame = self.cap.read()
                    if ret:
                        with self.lock:
                            self.latest_frame = frame
                    else:
                        time.sleep(0.02)
                else:
                    time.sleep(0.1)
        else:
            stream = self.stream
            buf = b""
            while self.running:
                try:
                    if stream is None:
                        req = urllib.request.Request(self.source, headers={'User-Agent': 'Mozilla/5.0'})
                        stream = urllib.request.urlopen(req, timeout=3.0)
                        self.stream = stream
                        buf = b""

                    chunk = stream.read(8192)
                    if not chunk:
                        time.sleep(0.01)
                        continue
                    buf += chunk

                    # Giới hạn bộ đệm tối đa 64KB để không bao giờ bị ứ đọng khung hình
                    if len(buf) > 65536:
                        soi_idx = buf.rfind(b'\xff\xd8')
                        if soi_idx != -1:
                            buf = buf[soi_idx:]
                        else:
                            buf = b""
                            continue

                    # Bóc tách và giải mã khung hình JPEG mới nhất
                    while True:
                        a = buf.find(b'\xff\xd8')
                        if a == -1:
                            buf = b""
                            break
                        b = buf.find(b'\xff\xd9', a + 2)
                        if b == -1:
                            buf = buf[a:]
                            break
                        jpg = buf[a:b+2]
                        buf = buf[b+2:]
                        decoded = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
                        if decoded is not None:
                            with self.lock:
                                self.latest_frame = decoded

                except Exception:
                    if stream:
                        try:
                            stream.close()
                        except Exception:
                            pass
                        stream = None
                        self.stream = None
                    time.sleep(0.1)

    def is_ready(self):
        with self.lock:
            has_frame = self.latest_frame is not None
        return self.ready and self.running and has_frame

    def read(self):
        with self.lock:
            if self.latest_frame is not None:
                return True, self.latest_frame.copy()
            return False, None

    def release(self):
        self.running = False
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
        if self.stream:
            try:
                self.stream.close()
            except Exception:
                pass

# ==========================================================
# CƠ SỞ DỮ LIỆU KHUÔN MẶT (HỖ TRỢ NHIỀU ẢNH / 1 SINH VIÊN)
# ==========================================================
def calculate_ear(eye_points):
    eye = np.array(eye_points)
    v1 = np.linalg.norm(eye[1] - eye[5])
    v2 = np.linalg.norm(eye[2] - eye[4])
    h = np.linalg.norm(eye[0] - eye[3])
    if h == 0:
        return 0.3
    return (v1 + v2) / (2.0 * h)

# MÔ HÌNH 3D NHÂN TRẮC HỌC KHUÔN MẶT (THEO NGHIÊN CỨU FACE ANTI-SPOOFING)
FACE_MODEL_3D = np.array([
    (0.0, 0.0, 0.0),          # Mũi (Nose tip)
    (0.0, -330.0, -65.0),     # Cằm (Chin)
    (-225.0, 170.0, -135.0),  # Khóe mắt ngoài bên trái
    (225.0, 170.0, -135.0),   # Khóe mắt ngoài bên phải
    (-150.0, -150.0, -125.0), # Khóe miệng bên trái
    (150.0, -150.0, -125.0)   # Khóe miệng bên phải
], dtype=np.float64)

DIST_COEFFS_ZERO = np.zeros((4, 1))

def estimate_head_pose_and_sym(lm, w=320, h=240):
    yaw, pitch, sym = 0.0, 0.0, 1.0
    try:
        # 1. Tính tỷ lệ đối xứng 2D (Symmetry Ratio)
        nose = np.array(lm['nose_tip'][2])
        left_eye = np.array(lm['left_eye'][0])
        right_eye = np.array(lm['right_eye'][3])
        d_left = np.linalg.norm(nose - left_eye)
        d_right = np.linalg.norm(nose - right_eye)
        sym = float(d_left / (d_right + 1e-6))
        
        # 2. Ước lượng góc xoay đầu 3D (3D Euler Angles qua solvePnP)
        img_pts = np.array([
            lm['nose_tip'][2],
            lm['chin'][8],
            lm['left_eye'][0],
            lm['right_eye'][3],
            lm['top_lip'][0],
            lm['top_lip'][6]
        ], dtype=np.float64)
        
        cam_mat = np.array([
            [float(w), 0.0, float(w)/2.0],
            [0.0, float(w), float(h)/2.0],
            [0.0, 0.0, 1.0]
        ], dtype=np.float64)
        
        success, rvec, _ = cv2.solvePnP(FACE_MODEL_3D, img_pts, cam_mat, DIST_COEFFS_ZERO, flags=cv2.SOLVEPNP_ITERATIVE)
        if success:
            R, _ = cv2.Rodrigues(rvec)
            sy = np.sqrt(R[0, 0]**2 + R[1, 0]**2)
            pitch = float(np.degrees(np.arctan2(R[2, 1], R[2, 2])))
            yaw = float(np.degrees(np.arctan2(-R[2, 0], sy)))
    except Exception:
        pass
    return yaw, pitch, sym

def analyze_passive_optical(face_crop):
    # Phân tích thụ động quang học: phát hiện màn hình điện thoại & ảnh bóng
    if face_crop is None or face_crop.size == 0:
        return True, "OK"
    h, w, _ = face_crop.shape
    total_px = h * w
    if total_px < 200:
        return True, "OK"
        
    # Phát hiện chói lóa bề mặt phẳng (Specular Glare)
    gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
    glare_ratio = float(np.sum(gray > 250)) / float(total_px)
    if glare_ratio > 0.12:
        return False, "Phát hiện màn hình/giấy bóng chói phản xạ"
        
    # Kiểm tra dải màu da tự nhiên (YCrCb Chrominance)
    ycrcb = cv2.cvtColor(face_crop, cv2.COLOR_BGR2YCrCb)
    cr = ycrcb[:, :, 1]
    cb = ycrcb[:, :, 2]
    skin_mask = (cr >= 125) & (cr <= 180) & (cb >= 70) & (cb <= 135)
    skin_ratio = float(np.sum(skin_mask)) / float(total_px)
    if skin_ratio < 0.15:
        return False, "Quang phổ màu da không tự nhiên"
        
    return True, "OK"

def match_student_from_filename(filename, roster_list):
    base_upper = filename.rsplit('.', 1)[0].upper()
    for s in roster_list:
        if s["id"] in base_upper:
            return s
    clean = re.sub(r'_\d+$', '', filename.rsplit('.', 1)[0]).replace('_', ' ')
    norm_name = remove_accents(clean)
    for s in roster_list:
        if remove_accents(s["name"]) == norm_name:
            if s["id"] == "B23DCAT153":
                return s
    for s in roster_list:
        if remove_accents(s["name"]) == norm_name:
            return s
    return None

roster = load_class_roster()

def get_faces_dir_mtime():
    face_dir = os.path.join(os.path.dirname(__file__), "faces")
    if os.path.exists(face_dir):
        files = os.listdir(face_dir)
        if files:
            return max(os.path.getmtime(os.path.join(face_dir, f)) for f in files)
    return 0

@st.cache_resource
def load_registered_faces(dir_mtime):
    known_encs = []
    known_students = []
    face_dir = os.path.join(os.path.dirname(__file__), "faces")
    if os.path.exists(face_dir):
        for fname in sorted(os.listdir(face_dir)):
            if fname.lower().endswith(('.jpg', '.jpeg', '.png')):
                fpath = os.path.join(face_dir, fname)
                st_match = match_student_from_filename(fname, roster)
                try:
                    img = face_recognition.load_image_file(fpath)
                    locs = face_recognition.face_locations(img)
                    if locs and st_match:
                        # Chọn khuôn mặt có diện tích lớn nhất (nhân vật chính)
                        locs.sort(key=lambda x: (x[2]-x[0])*(x[1]-x[3]), reverse=True)
                        encs = face_recognition.face_encodings(img, [locs[0]])
                        if encs:
                            known_encs.append(encs[0])
                            known_students.append(st_match)
                except Exception as e:
                    print(f"Lỗi nạp ảnh {fname}: {e}")
    return known_encs, known_students

known_encs, known_students = load_registered_faces(get_faces_dir_mtime())

# ==========================================================
# GIAO DIỆN CHÍNH
# ==========================================================
now = datetime.now()
time_text = now.strftime("%H:%M:%S")
date_text = now.strftime("Thứ %w, %d/%m/%Y").replace("Thứ 0", "Chủ Nhật")

st.markdown(f"""
<div class="header-bar">
    <div>
        <div class="header-school">HỌC VIỆN CÔNG NGHỆ BƯU CHÍNH VIỄN THÔNG • KHOA AN TOÀN THÔNG TIN</div>
        <div class="header-main-title">HỆ THỐNG ĐIỂM DANH SINH VIÊN AIoT</div>
        <div class="header-class-info">Học phần: IOT và ứng dụng (INT14149) • Nhóm lớp: INT14149-20261-CT02 • Lớp: D23CTAT01-B (Nhóm 05) • HK1 (2026 - 2027) • GVHD: TS. Lê Văn Vịnh</div>
    </div>
    <div>
        <div class="clock-display" id="live_clock_display">{time_text}</div>
        <div class="date-display" id="live_date_display">{date_text}</div>
    </div>
</div>
""", unsafe_allow_html=True)

# ĐỒNG HỒ THỜI GIAN THỰC NHẢY TỪNG GIÂY (CHẠY ĐỘC LẬP TRÊN TRÌNH DUYỆT)
components.html("""
<script>
function tick() {
    try {
        const pdoc = window.parent.document;
        const clk = pdoc.getElementById("live_clock_display");
        const dt = pdoc.getElementById("live_date_display");
        const now = new Date();
        const h = String(now.getHours()).padStart(2, '0');
        const m = String(now.getMinutes()).padStart(2, '0');
        const s = String(now.getSeconds()).padStart(2, '0');
        if (clk) clk.innerText = h + ":" + m + ":" + s;
        
        const days = ["Chủ Nhật", "Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7"];
        const dayStr = days[now.getDay()];
        const d = String(now.getDate()).padStart(2, '0');
        const mo = String(now.getMonth() + 1).padStart(2, '0');
        const y = now.getFullYear();
        if (dt) dt.innerText = dayStr + ", " + d + "/" + mo + "/" + y;
    } catch(e) {}
}
setInterval(tick, 1000);
tick();
</script>
""", height=0)

col_cam, col_table = st.columns([5, 7])

with col_cam:
    msg_box = st.empty()
    frame_box = st.empty()

with col_table:
    stat_box = st.empty()
    table_box = st.empty()
    
    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
    
    btn_col1, btn_col2, btn_col3 = st.columns(3)
    with btn_col1:
        att_dict = load_attendance_records()
        excel_data = create_excel_report(roster, att_dict)
        st.download_button(
            label="XUẤT EXCEL",
            data=excel_data,
            file_name=f"Diem_Danh_D23CTAT01B_{datetime.now().strftime('%d%m%Y')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    with btn_col2:
        if st.button("LÀM MỚI", use_container_width=True):
            update_roster_view()
            # Giữ nguyên camera_reader nếu đang kết nối bình thường, không ngắt socket ESP32
            cur_reader = st.session_state.get("camera_reader")
            if cur_reader is not None and not cur_reader.is_ready():
                try:
                    cur_reader.release()
                except Exception:
                    pass
                st.session_state["camera_reader"] = None
                st.session_state["camera_type"] = None
            st.rerun()
    with btn_col3:
        if st.button("RESET BUỔI MỚI", use_container_width=True):
            # Tự động sao lưu dữ liệu buổi cũ trước khi làm mới về 0/36
            if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 80:
                backup_name = os.path.join(
                    os.path.dirname(LOG_FILE),
                    f"attendance_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                )
                try:
                    shutil.copy(LOG_FILE, backup_name)
                except Exception:
                    pass
            # Khởi tạo lại bảng điểm danh rỗng (0/36)
            pd.DataFrame(columns=["Thời gian", "Mã SV", "Họ và Tên", "Trạng thái", "Xác thực"]).to_csv(LOG_FILE, index=False)
            update_roster_view()
            st.rerun()

def update_roster_view():
    current_att = load_attendance_records()
    present_cnt = 0
    tr_list = []
    
    for s in roster:
        is_p, t_txt = is_student_present(s, current_att)
        if is_p:
            present_cnt += 1
            time_display = t_txt.split(" ")[-1] if " " in t_txt else t_txt
            row_cls = "row-present"
            badge_cls = "badge-ok"
            stt_txt = "Có mặt"
        else:
            time_display = "-"
            row_cls = ""
            badge_cls = "badge-pending"
            stt_txt = "Chưa điểm danh"
            
        tr_list.append(
            f'<tr class="{row_cls}">'
            f'<td>{s["stt"]}</td>'
            f'<td><code>{s["id"]}</code></td>'
            f'<td><b>{s["name"]}</b></td>'
            f'<td>{s["dob"]}</td>'
            f'<td><span class="status-badge {badge_cls}">{stt_txt}</span></td>'
            f'<td>{time_display}</td>'
            f'</tr>'
        )
        
    absent_cnt = len(roster) - present_cnt
    
    stat_html = (
        '<div class="stat-container">'
        '<div class="stat-box stat-box-present">'
        f'<div class="stat-number" style="color: #047857;">{present_cnt} / {len(roster)}</div>'
        '<div class="stat-tag" style="color: #065F46;">CÓ MẶT</div>'
        '</div>'
        '<div class="stat-box stat-box-absent">'
        f'<div class="stat-number" style="color: #475569;">{absent_cnt}</div>'
        '<div class="stat-tag" style="color: #64748B;">CHƯA ĐIỂM DANH</div>'
        '</div>'
        '</div>'
    )
    stat_box.markdown(stat_html, unsafe_allow_html=True)
    
    tbl_html = (
        '<div class="table-wrapper">'
        '<table class="roster-table">'
        '<thead><tr>'
        '<th>STT</th>'
        '<th>Mã SV</th>'
        '<th>Họ và Tên</th>'
        '<th>Ngày sinh</th>'
        '<th>Trạng thái</th>'
        '<th>Giờ vào</th>'
        '</tr></thead>'
        '<tbody>'
        + "".join(tr_list) +
        '</tbody></table></div>'
    )
    table_box.markdown(tbl_html, unsafe_allow_html=True)

# Khởi tạo bảng ngay lần đầu
update_roster_view()

# ==========================================================
# KẾT NỐI VÀ TỰ ĐỘNG DÒ TÌM CAMERA
# ==========================================================
def find_active_camera():
    # 1. Quét luồng Wi-Fi ESP32-CAM tại 192.168.4.1:81/stream
    esp_reader = CameraReader("http://192.168.4.1:81/stream")
    if esp_reader.is_ready():
        return esp_reader, "ESP32-CAM (192.168.4.1)"
    esp_reader.release()

    # 2. Quét các thiết bị video cục bộ /dev/video0, /dev/video1, /dev/video2, /dev/video4
    for idx in [0, 1, 2, 4]:
        dev_node = f"/dev/video{idx}"
        if os.path.exists(dev_node):
            usb_reader = CameraReader(idx)
            if usb_reader.is_ready():
                return usb_reader, f"Webcam ({dev_node})"
            usb_reader.release()

    # 3. Thử mở cổng mặc định 0 nếu OpenCV hỗ trợ
    def_reader = CameraReader(0)
    if def_reader.is_ready():
        return def_reader, "Webcam (Port 0)"
    def_reader.release()

    return None, None

cap, cam_type = None, None

# QUẢN LÝ VÒNG ĐỜI CAMERA TRONG SESSION_STATE:
# Tránh mở lặp socket HTTP tới ESP32-CAM khi bấm "LÀM MỚI" hoặc Streamlit rerun
if "camera_reader" not in st.session_state or st.session_state["camera_reader"] is None or not st.session_state["camera_reader"].is_ready():
    cap, cam_type = find_active_camera()
    st.session_state["camera_reader"] = cap
    st.session_state["camera_type"] = cam_type
else:
    cap = st.session_state["camera_reader"]
    cam_type = st.session_state.get("camera_type", "Camera")

if cap is None or not cap.is_ready():
    st.session_state["camera_reader"] = None
    st.session_state["camera_type"] = None
    msg_box.markdown('<div class="message-banner msg-action">Chưa tìm thấy tín hiệu camera (ESP32-CAM hoặc Webcam)</div>', unsafe_allow_html=True)
    frame_box.markdown("""
    <div style="background: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 8px; padding: 22px; color: #1E293B; text-align: left;">
        <div style="font-size: 16px; font-weight: 800; color: #DC2626; margin-bottom: 12px; text-transform: uppercase;">
            TÍN HIỆU CAMERA CHƯA KẾT NỐI
        </div>
        <div style="font-size: 13px; line-height: 1.6; color: #334155;">
            Hệ thống đã dò tìm qua luồng Wi-Fi <b>http://192.168.4.1:81/stream</b> và các cổng Webcam <b>(/dev/video*)</b> nhưng chưa có tín hiệu.<br><br>
            <b>HƯỚNG DẪN KẾT NỐI THEO THIẾT BỊ:</b><br>
            • <b>Nếu dùng ESP32-CAM</b>: Cắm cáp USB vào máy tính chỉ có tác dụng cấp nguồn điện 5V. Bạn cần dùng máy tính kết nối vào mạng Wi-Fi do ESP32 phát ra: <b>ESP32_DIEM_DANH</b> (Mật khẩu: <code>12345678</code>).<br>
            • <b>Nếu dùng Webcam USB trên máy ảo VMware</b>: Mặc định máy thật (Windows) sẽ giữ webcam. Trên thanh menu VMware ở trên cùng, bạn bấm vào: <b>VM &rarr; Removable Devices &rarr; [Tên Webcam] &rarr; Connect (Disconnect from Host)</b>.<br><br>
            Sau khi kết nối thiết bị xong, bấm nút <b>LÀM MỚI</b> để camera hiển thị.
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.stop()
else:
    msg_box.markdown(f'<div class="message-banner msg-idle">Đã kết nối: <b>{cam_type}</b>. Sẵn sàng nhận diện.</div>', unsafe_allow_html=True)

# ==========================================================
# CẤU HÌNH THUẬT TOÁN FACE ANTI-SPOOFING (FAS) ĐA TẦNG
# DỰA TRÊN NGHIÊN CỨU: PASSIVE OPTICAL + ACTIVE RANDOMIZED CHALLENGE
# ==========================================================
EAR_OPEN_THRESH = 0.23     # Mắt mở bình thường
EAR_CLOSE_THRESH = 0.17    # Mắt nhắm hoàn toàn mí chạm mí
MIN_BLINK_DUR = 0.08       # Thời gian chớp mắt sinh học tối thiểu: 80ms
MAX_BLINK_DUR = 0.55       # Thời gian chớp mắt sinh học tối đa: 550ms
CHALLENGE_TIMEOUT = 4.0    # Hạn chót phản hồi thử thách (giây)
MAX_JUMP_PIXELS = 35       # Ngưỡng ổn định vị trí

# 3 Loại thử thách ngẫu nhiên thời gian thực (Randomized Active Challenges)
CHALLENGE_BLINK = "BLINK"              # Chớp mắt sinh học
CHALLENGE_TURN_RIGHT = "TURN_RIGHT"    # Quay nhẹ đầu sang phải
CHALLENGE_TURN_LEFT = "TURN_LEFT"      # Quay nhẹ đầu sang trái

STATE_WAIT_STABLE = 1         # Bước 1: Mở mắt, nhìn thẳng ổn định (Passive check)
STATE_PROMPT_CHALLENGE = 2    # Bước 2: Hiển thị lệnh thử thách ngẫu nhiên
STATE_ACTION_IN_PROGRESS = 3  # Bước 3: Đang thực hiện (mắt nhắm hoặc đầu đang quay)
STATE_PASSED = 4              # Bước 4: Hoàn thành xác thực người thật

liveness_state = STATE_WAIT_STABLE
stable_start_time = None
prompt_time = None
action_start_time = None
active_challenge = CHALLENGE_BLINK

tracking_name = None
last_name = None
last_time = 0
last_center = None

frame_idx = 0
cached_student = None
last_enc_time = 0
candidates = []
target = None

msg_box.markdown('<div class="message-banner msg-idle">Sẵn sàng nhận diện. Vui lòng nhìn thẳng vào camera.</div>', unsafe_allow_html=True)

while cap is not None:
    ret, frame = cap.read()
    if not ret or frame is None:
        time.sleep(0.02)
        continue

    frame_idx += 1
    h, w, _ = frame.shape
    min_face_area = int(w * h * 0.03)  # Ngưỡng diện tích tối thiểu (loại người ở xa > 2m)

    # Khung căn giữa
    cx1, cy1 = int(w * 0.22), int(h * 0.15)
    cx2, cy2 = int(w * 0.78), int(h * 0.85)
    cv2.rectangle(frame, (cx1, cy1), (cx2, cy2), (245, 158, 11), 2)
    cv2.putText(frame, "CAN GIUA KHUNG HINH", (cx1 + 8, cy1 - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (245, 158, 11), 1)

    # Nhận diện vị trí và điểm mốc mí mắt mỗi khung hình để không bỏ sót chuyển động chớp mắt
    scale = 0.35
    small = cv2.resize(frame, (0, 0), fx=scale, fy=scale)
    rgb_small = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)

    face_locs = face_recognition.face_locations(rgb_small)
    candidates = []

    if face_locs:
        landmarks = face_recognition.face_landmarks(rgb_small, face_locs)
        for idx, loc in enumerate(face_locs):
            top, right, bottom, left = loc
            ot, oright, ob, ol = int(top/scale), int(right/scale), int(bottom/scale), int(left/scale)
            area = (oright - ol) * (ob - ot)

            ear_val = 0.3
            yaw_val = 0.0
            pitch_val = 0.0
            sym_val = 1.0
            if idx < len(landmarks):
                lm = landmarks[idx]
                if 'left_eye' in lm and 'right_eye' in lm:
                    el = calculate_ear(lm['left_eye'])
                    er = calculate_ear(lm['right_eye'])
                    ear_val = (el + er) / 2.0
                if 'nose_tip' in lm and 'chin' in lm and 'top_lip' in lm:
                    yaw_val, pitch_val, sym_val = estimate_head_pose_and_sym(lm, w=int(w*scale), h=int(h*scale))

            center_x = (ol + oright) // 2
            center_y = (ot + ob) // 2
            is_centered = (cx1 <= center_x <= cx2) and (cy1 <= center_y <= cy2)

            candidates.append({
                "loc": (ot, oright, ob, ol),
                "small_loc": loc,
                "area": area,
                "center": (center_x, center_y),
                "is_centered": is_centered,
                "ear": ear_val,
                "yaw": yaw_val,
                "pitch": pitch_val,
                "sym": sym_val
            })

    target = None
    # ĐIỀU KIỆN 1: Khóa đối tượng gần nhất dựa theo diện tích khuôn mặt lớn nhất
    if candidates:
        candidates.sort(key=lambda x: x["area"], reverse=True)
        target = candidates[0]

    if target:
        bx, by = target["loc"][3], target["loc"][0]
        bw = target["loc"][1] - target["loc"][3]
        bh = target["loc"][2] - target["loc"][0]
        cur_center = target["center"]

        # TẦNG 2: PHÂN TÍCH QUANG HỌC THỤ ĐỘNG (PASSIVE OPTICAL ANALYSIS)
        face_crop = frame[max(0, by):min(h, by+bh), max(0, bx):min(w, bx+bw)]
        is_passive_safe, passive_reason = analyze_passive_optical(face_crop)

        # Kiểm tra ngưỡng diện tích tối thiểu
        if target["area"] < min_face_area:
            tracking_name = None
            last_center = None
            cached_student = None
            liveness_state = STATE_WAIT_STABLE
            stable_start_time = None
            prompt_time = None
            action_start_time = None
            active_challenge = CHALLENGE_BLINK
            msg_box.markdown('<div class="message-banner msg-action">Vui lòng bước lại gần camera hơn để điểm danh</div>', unsafe_allow_html=True)
            cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), (148, 163, 184), 1)
            cv2.putText(frame, "QUA XA", (bx, by - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (148, 163, 184), 1)

        # ĐIỀU KIỆN 2: Bắt buộc tâm khuôn mặt nằm trong vùng ROI trung tâm
        elif not target["is_centered"]:
            tracking_name = None
            last_center = None
            cached_student = None
            liveness_state = STATE_WAIT_STABLE
            stable_start_time = None
            prompt_time = None
            action_start_time = None
            active_challenge = CHALLENGE_BLINK
            msg_box.markdown('<div class="message-banner msg-action">Vui lòng bước vào chính giữa khung hình</div>', unsafe_allow_html=True)
            cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), (0, 100, 255), 2)
            cv2.putText(frame, "LECH TRUNG TAM", (bx, by - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 100, 255), 1)

        # Kiểm tra chói lóa màn hình hoặc bề mặt giả mạo (Passive Spoof)
        elif not is_passive_safe:
            tracking_name = None
            last_center = None
            cached_student = None
            liveness_state = STATE_WAIT_STABLE
            stable_start_time = None
            prompt_time = None
            action_start_time = None
            active_challenge = CHALLENGE_BLINK
            msg_box.markdown(f'<div class="message-banner msg-action">Cảnh báo FAS: {passive_reason}. Vui lòng không dùng màn hình/ảnh in.</div>', unsafe_allow_html=True)
            cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), (0, 0, 255), 2)
            cv2.putText(frame, "CANH BAO GIA MAO", (bx, by - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)

        else:
            # ĐIỀU KIỆN 3: Kiểm tra độ ổn định vị trí (Temporal Stability)
            if last_center is not None:
                dist_jump = np.linalg.norm(np.array(cur_center) - np.array(last_center))
                if dist_jump > MAX_JUMP_PIXELS:
                    liveness_state = STATE_WAIT_STABLE
                    stable_start_time = None
                    prompt_time = None
                    action_start_time = None
                    active_challenge = CHALLENGE_BLINK
                    cached_student = None
            last_center = cur_center

            # Trích xuất vector ResNet-34 chỉ khi chưa nhận diện hoặc định kỳ 2s
            now_t = time.time()
            if cached_student is None or (now_t - last_enc_time > 2.0):
                face_encs = face_recognition.face_encodings(rgb_small, [target["small_loc"]])
                cached_student = None
                last_enc_time = now_t

                if face_encs and len(known_encs) > 0:
                    matches = face_recognition.compare_faces(known_encs, face_encs[0], tolerance=0.52)
                    dists = face_recognition.face_distance(known_encs, face_encs[0])
                    best_idx = np.argmin(dists)
                    if matches[best_idx]:
                        cached_student = known_students[best_idx]

            matched_student = cached_student

            if matched_student is None:
                tracking_name = None
                liveness_state = STATE_WAIT_STABLE
                stable_start_time = None
                prompt_time = None
                action_start_time = None
                active_challenge = CHALLENGE_BLINK
                msg_box.markdown('<div class="message-banner msg-action">Khuôn mặt chưa có trong danh sách đăng ký của lớp</div>', unsafe_allow_html=True)
                cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), (0, 140, 255), 2)
                cv2.putText(frame, "CHUA DANG KY", (bx, by - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 140, 255), 1)
            else:
                official_name = matched_student["name"]
                official_id = matched_student["id"]

                if tracking_name != official_name:
                    tracking_name = official_name
                    liveness_state = STATE_WAIT_STABLE
                    stable_start_time = None
                    prompt_time = None
                    action_start_time = None
                    active_challenge = CHALLENGE_BLINK

                cur_ear = target["ear"]
                cur_yaw = target["yaw"]
                cur_sym = target["sym"]

                # ======================================================
                # MÁY TRẠNG THÁI THỬ THÁCH NGẪU NHIÊN THỜI GIAN THỰC
                # (RANDOMIZED ACTIVE CHALLENGE-RESPONSE STATE MACHINE)
                # ======================================================
                if liveness_state == STATE_WAIT_STABLE:
                    # Yêu cầu nhìn thẳng và mở mắt tự nhiên (Yaw trong khoảng +-12 độ)
                    is_facing_straight = (-12.0 <= cur_yaw <= 12.0) and (0.80 <= cur_sym <= 1.35)
                    if is_facing_straight and (cur_ear >= EAR_OPEN_THRESH):
                        if stable_start_time is None:
                            stable_start_time = now_t
                        elif (now_t - stable_start_time) >= 0.35:
                            # Đã nhìn thẳng ổn định >= 0.35s -> Bốc thăm ngẫu nhiên 1 trong 3 thử thách
                            active_challenge = random.choice([
                                CHALLENGE_BLINK,
                                CHALLENGE_BLINK,
                                CHALLENGE_TURN_RIGHT,
                                CHALLENGE_TURN_LEFT
                            ])
                            liveness_state = STATE_PROMPT_CHALLENGE
                            prompt_time = now_t
                    else:
                        stable_start_time = None

                    msg_box.markdown(f'<div class="message-banner msg-process">Đang nhận diện: <b>{official_name}</b>... Mở mắt nhìn thẳng camera</div>', unsafe_allow_html=True)
                    cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), (0, 200, 255), 2)
                    cv2.putText(frame, f"{official_name} | MO MAT NHIN THANG", (bx, by - 8),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 255), 2)

                elif liveness_state == STATE_PROMPT_CHALLENGE:
                    # Kiểm tra quá hạn thử thách (sau 4 giây không thực hiện -> reset để tránh treo)
                    if (now_t - prompt_time) > CHALLENGE_TIMEOUT:
                        liveness_state = STATE_WAIT_STABLE
                        stable_start_time = None
                        msg_box.markdown(f'<div class="message-banner msg-action">Quá thời gian xác thực FAS ({official_name}). Vui lòng thử lại.</div>', unsafe_allow_html=True)
                    else:
                        # 1. THỬ THÁCH CHỚP MẮT SINH HỌC
                        if active_challenge == CHALLENGE_BLINK:
                            if cur_ear <= EAR_CLOSE_THRESH:
                                liveness_state = STATE_ACTION_IN_PROGRESS
                                action_start_time = now_t
                                msg_box.markdown(f'<div class="message-banner msg-action">Xác thực FAS: <b>{official_name}</b> — Đang kiểm tra mí mắt...</div>', unsafe_allow_html=True)
                                cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), (0, 165, 255), 2)
                                cv2.putText(frame, f"{official_name} | DANG KIEM TRA MI MAT", (bx, by - 8),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 165, 255), 2)
                            else:
                                msg_box.markdown(f'<div class="message-banner msg-action">Thử thách FAS: <b>{official_name}</b> — Vui lòng CHỚP MẮT để xác nhận người thật!</div>', unsafe_allow_html=True)
                                cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), (0, 165, 255), 2)
                                cv2.putText(frame, f"{official_name} | CHOP MAT NGAY", (bx, by - 8),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 165, 255), 2)

                        # 2. THỬ THÁCH QUAY NHẸ ĐẦU SANG PHẢI
                        elif active_challenge == CHALLENGE_TURN_RIGHT:
                            if (cur_yaw > 13.0) or (cur_sym > 1.45):
                                liveness_state = STATE_ACTION_IN_PROGRESS
                                action_start_time = now_t
                                msg_box.markdown(f'<div class="message-banner msg-action">Xác thực FAS: <b>{official_name}</b> — Tốt lắm! Hãy nhìn thẳng lại camera...</div>', unsafe_allow_html=True)
                                cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), (0, 165, 255), 2)
                                cv2.putText(frame, f"{official_name} | QUAY THANG LAI", (bx, by - 8),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 165, 255), 2)
                            else:
                                msg_box.markdown(f'<div class="message-banner msg-action">Thử thách FAS: <b>{official_name}</b> — Vui lòng QUAY NHẸ ĐẦU SANG PHẢI (➜)!</div>', unsafe_allow_html=True)
                                cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), (0, 165, 255), 2)
                                cv2.putText(frame, f"{official_name} | QUAY SANG PHAI >>", (bx, by - 8),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 165, 255), 2)

                        # 3. THỬ THÁCH QUAY NHẸ ĐẦU SANG TRÁI
                        elif active_challenge == CHALLENGE_TURN_LEFT:
                            if (cur_yaw < -13.0) or (cur_sym < 0.70):
                                liveness_state = STATE_ACTION_IN_PROGRESS
                                action_start_time = now_t
                                msg_box.markdown(f'<div class="message-banner msg-action">Xác thực FAS: <b>{official_name}</b> — Tốt lắm! Hãy nhìn thẳng lại camera...</div>', unsafe_allow_html=True)
                                cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), (0, 165, 255), 2)
                                cv2.putText(frame, f"{official_name} | QUAY THANG LAI", (bx, by - 8),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 165, 255), 2)
                            else:
                                msg_box.markdown(f'<div class="message-banner msg-action">Thử thách FAS: <b>{official_name}</b> — Vui lòng QUAY NHẸ ĐẦU SANG TRÁI (⬅)!</div>', unsafe_allow_html=True)
                                cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), (0, 165, 255), 2)
                                cv2.putText(frame, f"{official_name} | << QUAY SANG TRAI", (bx, by - 8),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 165, 255), 2)

                elif liveness_state == STATE_ACTION_IN_PROGRESS:
                    dur = now_t - action_start_time
                    if active_challenge == CHALLENGE_BLINK:
                        if dur > MAX_BLINK_DUR:
                            liveness_state = STATE_WAIT_STABLE
                            stable_start_time = None
                            msg_box.markdown(f'<div class="message-banner msg-action">Không hợp lệ: Mắt nhắm quá lâu (>0.5s). Vui lòng thử lại.</div>', unsafe_allow_html=True)
                        elif cur_ear >= EAR_OPEN_THRESH:
                            if MIN_BLINK_DUR <= dur <= MAX_BLINK_DUR:
                                liveness_state = STATE_PASSED
                            else:
                                liveness_state = STATE_WAIT_STABLE
                                stable_start_time = None
                        else:
                            cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), (0, 165, 255), 2)
                            cv2.putText(frame, f"{official_name} | DANG KIEM TRA MI MAT", (bx, by - 8),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 165, 255), 2)
                    else: # TURN_RIGHT hoặc TURN_LEFT
                        if dur > 3.0:
                            liveness_state = STATE_WAIT_STABLE
                            stable_start_time = None
                            msg_box.markdown(f'<div class="message-banner msg-action">Quá thời gian nhìn thẳng lại. Vui lòng thử lại.</div>', unsafe_allow_html=True)
                        elif (-9.0 <= cur_yaw <= 9.0) and (0.85 <= cur_sym <= 1.25):
                            # Đã quay đầu trở lại vị trí nhìn thẳng trung tâm thành công!
                            liveness_state = STATE_PASSED
                        else:
                            msg_box.markdown(f'<div class="message-banner msg-action">Xác thực FAS: <b>{official_name}</b> — Rất tốt! Hãy nhìn thẳng lại camera...</div>', unsafe_allow_html=True)
                            cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), (0, 165, 255), 2)
                            cv2.putText(frame, f"{official_name} | QUAY THANG LAI", (bx, by - 8),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 165, 255), 2)

                if liveness_state == STATE_PASSED:
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    if (last_name != official_name) or (time.time() - last_time > 15):
                        new_row = pd.DataFrame([{
                            "Thời gian": now_str,
                            "Mã SV": official_id,
                            "Họ và Tên": official_name,
                            "Trạng thái": "Có mặt",
                            "Xác thực": f"Khuôn mặt + FAS ({active_challenge})"
                        }])
                        new_row.to_csv(LOG_FILE, mode='a', header=False, index=False)
                        last_name = official_name
                        last_time = time.time()
                        update_roster_view()
                        play_attendance_beep()

                    msg_box.markdown(f'<div class="message-banner msg-success">Đã điểm danh: <b>{official_name}</b> ({official_id}) lúc {now_str.split(" ")[-1]} [Xác thực FAS thành công]</div>', unsafe_allow_html=True)
                    cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), (0, 255, 0), 2)
                    cv2.putText(frame, f"CO MAT | FAS PASSED ({active_challenge})", (bx, by + bh + 25),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)

        # Hiển thị Telemetry HUD ở góc trên bên trái khung hình camera
        cv2.rectangle(frame, (10, 10), (330, 42), (15, 23, 42), -1)
        cv2.putText(frame, f"FAS: ACTIVE | Yaw: {target['yaw']:+.1f} deg | EAR: {target['ear']:.2f}",
                    (18, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (34, 197, 94), 1)
    else:
        tracking_name = None
        last_center = None
        cached_student = None
        liveness_state = STATE_WAIT_STABLE
        stable_start_time = None
        prompt_time = None
        action_start_time = None
        active_challenge = CHALLENGE_BLINK
        msg_box.markdown('<div class="message-banner msg-idle">Sẵn sàng nhận diện. Vui lòng nhìn thẳng vào camera.</div>', unsafe_allow_html=True)
        cv2.rectangle(frame, (10, 10), (330, 42), (15, 23, 42), -1)
        cv2.putText(frame, "FAS: ACTIVE (3D POSE + MULTI-CHALLENGE)", (18, 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (148, 163, 184), 1)

    frame_box.image(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), channels="RGB", use_container_width=True)
    time.sleep(0.01)

cap.release()
