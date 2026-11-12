// Tầng Cloud của BTL IoT Nhóm 05: lưu trữ điểm danh, thống kê chuyên cần, hàng lệnh gửi ngược xuống nút camera.
// Cách dùng: mở một Google Sheet mới > Extensions > Apps Script > dán toàn bộ file này > đổi TOKEN > Deploy (Web app).
// Gateway (laptop) gửi POST JSON vào URL /exec. Mọi tính toán thống kê chạy trên máy chủ Google.

const TOKEN = 'DOI_CHUOI_NAY';          // phải trùng CLOUD_SYNC_TOKEN trong file .env của gateway
const NGUONG_VANG = 2;                   // vắng từ ngần này buổi trở lên thì ghi cảnh báo

const COT_DIEM_DANH = ['event_id', 'thoi_gian', 'ma_sv', 'ho_ten', 'lop', 'session_id', 'buoi_hoc',
                       'trang_thai', 'thiet_bi', 'xac_minh', 'gateway', 'cloud_nhan_luc'];
const COT_THIET_BI = ['device_id', 'ten', 'trang_thai', 'lan_cuoi_thay', 'gateway', 'cloud_cap_nhat'];
const COT_LENH = ['id', 'device_id', 'lenh', 'gia_tri', 'trang_thai', 'ket_qua', 'xong_luc'];
const COT_TK_BUOI = ['session_id', 'buoi_hoc', 'lop', 'co_mat', 'di_muon', 'vang', 'tong', 'ty_le_chuyen_can_%'];
const COT_TK_SV = ['ma_sv', 'ho_ten', 'lop', 'so_buoi', 'co_mat', 'di_muon', 'vang', 'canh_bao'];

function doPost(e) {
  let body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return tra_({ ok: false, error: 'json' });
  }
  if (!body || body.token !== TOKEN) return tra_({ ok: false, error: 'token' });

  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const gateway = String(body.gateway_id || '');
    const them = ghiDiemDanh_(ss, body.attendance || [], gateway);
    ghiThietBi_(ss, body.devices || [], gateway);
    ghiKetQuaLenh_(ss, body.command_results || []);
    if (them > 0) capNhatThongKe_(ss);
    return tra_({ ok: true, added: them, commands: lenhCho_(ss) });
  } catch (err) {
    return tra_({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}

// GET không tham số: kiểm tra dịch vụ còn sống. GET ?action=stats&token=...: trả thống kê dạng JSON.
function doGet(e) {
  const p = (e && e.parameter) || {};
  if (p.action !== 'stats') return tra_({ ok: true, service: 'btl-iot-nhom05-cloud' });
  if (p.token !== TOKEN) return tra_({ ok: false, error: 'token' });
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  return tra_({ ok: true, theo_buoi: docBang_(ss, 'ThongKeBuoi'), theo_sinh_vien: docBang_(ss, 'ThongKeSV') });
}

function tra_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function sheet_(ss, ten, cot) {
  let sh = ss.getSheetByName(ten);
  if (!sh) {
    sh = ss.insertSheet(ten);
    sh.getRange(1, 1, 1, cot.length).setValues([cot]).setFontWeight('bold');
    sh.setFrozenRows(1);
  }
  return sh;
}

// Chuỗi bắt đầu bằng = + - @ sẽ bị Sheets hiểu là công thức; thêm dấu nháy để giữ nguyên là chữ.
function chu_(v) {
  const s = v === null || v === undefined ? '' : String(v);
  return /^[=+\-@]/.test(s) ? "'" + s : s;
}

function ghiDiemDanh_(ss, rows, gateway) {
  const sh = sheet_(ss, 'DiemDanh', COT_DIEM_DANH);
  if (!rows.length) return 0;
  const n = sh.getLastRow();
  const daCo = new Set(n > 1 ? sh.getRange(2, 1, n - 1, 1).getValues().map(function (r) { return String(r[0]); }) : []);
  const moi = [];
  rows.forEach(function (r) {
    const id = String(r.event_id || '');
    if (!id || daCo.has(id)) return;
    daCo.add(id);
    moi.push([chu_(id), chu_(r.checked_at), chu_(r.student_code), chu_(r.student_name), chu_(r.class_code),
              Number(r.session_id) || 0, chu_(r.session_title), chu_(r.status), chu_(r.device_id),
              chu_(r.verification), chu_(gateway), new Date()]);
  });
  if (moi.length) sh.getRange(n + 1, 1, moi.length, COT_DIEM_DANH.length).setValues(moi);
  return moi.length;
}

function ghiThietBi_(ss, devices, gateway) {
  const sh = sheet_(ss, 'ThietBi', COT_THIET_BI);
  if (!devices.length) return;
  const n = sh.getLastRow();
  const dong = {};
  if (n > 1) {
    sh.getRange(2, 1, n - 1, 1).getValues().forEach(function (r, i) { dong[String(r[0])] = i + 2; });
  }
  let cuoi = n;
  devices.forEach(function (d) {
    const id = String(d.device_id || '');
    if (!id) return;
    const gia = [[chu_(id), chu_(d.name), chu_(d.status), chu_(d.last_seen), chu_(gateway), new Date()]];
    if (!dong[id]) { cuoi += 1; dong[id] = cuoi; }
    sh.getRange(dong[id], 1, 1, COT_THIET_BI.length).setValues(gia);
  });
}

// Người điều khiển gõ một dòng vào sheet Lenh (cột device_id, lenh, gia_tri). Dòng chưa có trang_thai là lệnh đang chờ.
function lenhCho_(ss) {
  const sh = sheet_(ss, 'Lenh', COT_LENH);
  const n = sh.getLastRow();
  if (n < 2) return [];
  const data = sh.getRange(2, 1, n - 1, COT_LENH.length).getValues();
  const ra = [];
  data.forEach(function (r, i) {
    const lenh = String(r[2] || '').trim();
    if (!lenh || String(r[4] || '').trim()) return;
    const hang = i + 2;
    sh.getRange(hang, 1).setValue(hang);
    sh.getRange(hang, 5).setValue('da_gui');
    ra.push({ id: hang, device_id: String(r[1] || '').trim(), lenh: lenh, gia_tri: String(r[3] || '').trim() });
  });
  return ra;
}

function ghiKetQuaLenh_(ss, results) {
  if (!results.length) return;
  const sh = sheet_(ss, 'Lenh', COT_LENH);
  const n = sh.getLastRow();
  results.forEach(function (r) {
    const hang = Number(r.id);
    if (!(hang >= 2 && hang <= n)) return;
    sh.getRange(hang, 5, 1, 3).setValues([[r.ok ? 'xong' : 'loi', chu_(r.detail), new Date()]]);
  });
}

// Phân tích trên cloud: đọc toàn bộ sheet DiemDanh, tính lại hai bảng thống kê.
function capNhatThongKe_(ss) {
  const rows = docBang_(ss, 'DiemDanh');
  const buoi = {}, sv = {};
  rows.forEach(function (r) {
    const b = buoi[r.session_id] = buoi[r.session_id] ||
      { session_id: r.session_id, buoi_hoc: r.buoi_hoc, lop: r.lop, co_mat: 0, di_muon: 0, vang: 0 };
    const s = sv[r.ma_sv] = sv[r.ma_sv] ||
      { ma_sv: r.ma_sv, ho_ten: r.ho_ten, lop: r.lop, co_mat: 0, di_muon: 0, vang: 0 };
    const cot = r.trang_thai === 'absent' ? 'vang' : (r.trang_thai === 'late' ? 'di_muon' : 'co_mat');
    b[cot] += 1;
    s[cot] += 1;
  });
  const bangBuoi = Object.keys(buoi).map(function (k) {
    const b = buoi[k], tong = b.co_mat + b.di_muon + b.vang;
    return [b.session_id, b.buoi_hoc, b.lop, b.co_mat, b.di_muon, b.vang, tong,
            tong ? Math.round((b.co_mat + b.di_muon) * 1000 / tong) / 10 : 0];
  });
  const bangSv = Object.keys(sv).map(function (k) {
    const s = sv[k], tong = s.co_mat + s.di_muon + s.vang;
    return [s.ma_sv, s.ho_ten, s.lop, tong, s.co_mat, s.di_muon, s.vang,
            s.vang >= NGUONG_VANG ? 'Vắng ' + s.vang + ' buổi' : ''];
  }).sort(function (a, b) { return b[6] - a[6]; });
  ghiBang_(ss, 'ThongKeBuoi', COT_TK_BUOI, bangBuoi);
  ghiBang_(ss, 'ThongKeSV', COT_TK_SV, bangSv);
}

function ghiBang_(ss, ten, cot, data) {
  const sh = sheet_(ss, ten, cot);
  const n = sh.getLastRow();
  if (n > 1) sh.getRange(2, 1, n - 1, cot.length).clearContent();
  if (data.length) sh.getRange(2, 1, data.length, cot.length).setValues(data);
}

function docBang_(ss, ten) {
  const sh = ss.getSheetByName(ten);
  if (!sh || sh.getLastRow() < 2) return [];
  const v = sh.getDataRange().getValues();
  const cot = v[0];
  return v.slice(1).map(function (r) {
    const o = {};
    cot.forEach(function (c, i) { o[c] = r[i]; });
    return o;
  });
}
