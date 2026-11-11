import { useState, useEffect, useCallback, useMemo, useRef, ChangeEvent, FormEvent } from "react";
import { ApiFn, downloadFile, makeRawApi, uploadImport, ImportResult } from "./fileTransfer";

export type ScheduleItem = {
  id: number;
  class_id: number;
  class_code: string;
  title: string;
  date: string;
  start_time: string;
  end_time: string;
  room: string | null;
  note: string | null;
  session_id: number | null;
  session_status: string | null;
};

type PreviewRow = {
  row?: number;
  class_code?: string;
  title?: string;
  date?: string;
  start_time?: string;
  end_time?: string;
  room?: string | null;
  action?: string;
};

type ScheduleImportResult = ImportResult & {
  filtered_out?: number;
};

interface SchedulePanelProps {
  api: ApiFn;
  apiUrl: string;
  token: string;
  classes: { id: number; code: string; name: string }[];
  onSessionCreated: (sessionId: number) => void;
}

function toDateString(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function getDefaultDateRange(): { from: string; to: string } {
  const now = new Date();
  const day = now.getDay();
  // Thứ Hai tuần này: Chủ nhật (0) lùi 6 ngày, các ngày khác lùi (day - 1) ngày
  const diffToMonday = day === 0 ? -6 : 1 - day;
  const monday = new Date(now.getFullYear(), now.getMonth(), now.getDate() + diffToMonday);
  // Hết 4 tuần sau: tuần này + 4 tuần tiếp theo kết thúc vào Chủ nhật (+34 ngày tính từ Thứ Hai)
  const toDate = new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + 34);
  return {
    from: toDateString(monday),
    to: toDateString(toDate),
  };
}

function formatDateHeader(dateStr: string): string {
  const parts = dateStr.split("-");
  if (parts.length !== 3) return dateStr;
  const y = Number(parts[0]);
  const m = Number(parts[1]);
  const d = Number(parts[2]);
  const dt = new Date(y, m - 1, d);
  const DAYS = ["Chủ Nhật", "Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy"];
  const dayOfWeek = DAYS[dt.getDay()] || "Thứ Hai";
  const dd = String(d).padStart(2, "0");
  const mm = String(m).padStart(2, "0");
  return `${dayOfWeek}, ${dd}/${mm}/${y}`;
}

function renderSessionBadge(status: string | null, sessionId: number | null) {
  if (!sessionId) {
    return <span className="badge">Chưa tạo</span>;
  }
  switch (status) {
    case "draft":
      return <span className="badge draft">Nháp</span>;
    case "open":
      return <span className="badge open">Đang mở</span>;
    case "closed":
      return <span className="badge closed">Đã đóng</span>;
    default:
      return <span className="badge">{status || "Nháp"}</span>;
  }
}

export default function SchedulePanel(props: SchedulePanelProps) {
  const { from: defaultFrom, to: defaultTo } = useMemo(() => getDefaultDateRange(), []);

  // Filter state
  const [classFilter, setClassFilter] = useState<string>("");
  const [dateFrom, setDateFrom] = useState<string>(defaultFrom);
  const [dateTo, setDateTo] = useState<string>(defaultTo);

  // Data & status
  const [schedules, setSchedules] = useState<ScheduleItem[]>([]);
  const [busy, setBusy] = useState<boolean>(false);
  const [error, setError] = useState<string>("");
  const [notice, setNotice] = useState<string>("");

  // Form state
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editingClassId, setEditingClassId] = useState<number | null>(null);
  const [formTitle, setFormTitle] = useState<string>("");
  const [formDate, setFormDate] = useState<string>(toDateString(new Date()));
  const [formStartTime, setFormStartTime] = useState<string>("07:00");
  const [formEndTime, setFormEndTime] = useState<string>("09:00");
  const [formRoom, setFormRoom] = useState<string>("");
  const [formNote, setFormNote] = useState<string>("");

  // Import state
  const [importFile, setImportFile] = useState<File | null>(null);
  const [onConflict, setOnConflict] = useState<"skip" | "update">("skip");
  const [keywordFilter, setKeywordFilter] = useState<string>("");
  const [importResult, setImportResult] = useState<ScheduleImportResult | null>(null);
  const importInputRef = useRef<HTMLInputElement>(null);

  const rawApi = useMemo(() => makeRawApi(props.apiUrl, props.token), [props.apiUrl, props.token]);

  // Load schedules
  const loadSchedules = useCallback(async () => {
    setError("");
    setBusy(true);
    try {
      const params = new URLSearchParams();
      if (classFilter) params.set("class_id", classFilter);
      if (dateFrom) params.set("date_from", dateFrom);
      if (dateTo) params.set("date_to", dateTo);
      const query = params.toString() ? `?${params.toString()}` : "";
      const res = await props.api(`/schedules${query}`);
      const data = (await res.json()) as ScheduleItem[];
      setSchedules(data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg || "Không thể tải danh sách lịch học");
    } finally {
      setBusy(false);
    }
  }, [props.api, classFilter, dateFrom, dateTo]);

  useEffect(() => {
    void loadSchedules();
  }, [loadSchedules]);

  // Group schedules by date
  const groupedSchedules = useMemo(() => {
    const map = new Map<string, ScheduleItem[]>();
    for (const item of schedules) {
      const list = map.get(item.date) || [];
      list.push(item);
      map.set(item.date, list);
    }
    return Array.from(map.entries());
  }, [schedules]);

  // Name of currently selected class in filter
  const currentSelectedClass = useMemo(() => {
    return props.classes.find((c) => String(c.id) === classFilter) || null;
  }, [props.classes, classFilter]);

  // Name of class being edited
  const editingClass = useMemo(() => {
    if (!editingClassId) return null;
    return props.classes.find((c) => c.id === editingClassId) || null;
  }, [props.classes, editingClassId]);

  // Cancel form edit
  const handleCancelEdit = () => {
    setEditingId(null);
    setEditingClassId(null);
    setFormTitle("");
    setFormDate(toDateString(new Date()));
    setFormStartTime("07:00");
    setFormEndTime("09:00");
    setFormRoom("");
    setFormNote("");
    setError("");
  };

  // Start edit
  const handleStartEdit = (item: ScheduleItem) => {
    if (item.session_status === "open" || item.session_status === "closed") {
      setError("Buổi điểm danh đã mở hoặc đã đóng, không thể sửa lịch học.");
      return;
    }
    setError("");
    setNotice("");
    setEditingId(item.id);
    setEditingClassId(item.class_id);
    setFormTitle(item.title);
    setFormDate(item.date);
    setFormStartTime(item.start_time);
    setFormEndTime(item.end_time);
    setFormRoom(item.room || "");
    setFormNote(item.note || "");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  // Delete schedule
  const handleDelete = async (item: ScheduleItem) => {
    if (item.session_status === "open" || item.session_status === "closed") {
      setError("Buổi điểm danh đã mở hoặc đã đóng, không thể xóa lịch học.");
      return;
    }
    if (!confirm(`Xóa lịch học "${item.title}" (${item.date} ${item.start_time})?`)) {
      return;
    }
    setError("");
    setNotice("");
    setBusy(true);
    try {
      await props.api(`/schedules/${item.id}`, { method: "DELETE" });
      setNotice(`Đã xóa lịch học "${item.title}".`);
      if (editingId === item.id) {
        handleCancelEdit();
      }
      await loadSchedules();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg || "Không thể xóa lịch học");
    } finally {
      setBusy(false);
    }
  };

  // Create session from schedule
  const handleCreateSession = async (scheduleId: number) => {
    setError("");
    setNotice("");
    setBusy(true);
    try {
      const res = await props.api(`/schedules/${scheduleId}/create-session`, {
        method: "POST",
      });
      const sessionData = (await res.json()) as { id: number; title: string; status: string };
      setNotice(`Đã tạo buổi điểm danh #${sessionData.id} cho lịch học.`);
      await loadSchedules();
      props.onSessionCreated(sessionData.id);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg || "Không thể tạo buổi điểm danh");
    } finally {
      setBusy(false);
    }
  };

  // Form submit (Add / Edit)
  const handleFormSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setNotice("");

    const targetClassId = editingId ? editingClassId : (classFilter ? Number(classFilter) : null);
    if (!targetClassId) {
      setError("Vui lòng chọn một lớp học cụ thể ở bộ lọc phía trên để thêm lịch.");
      return;
    }

    if (!formTitle.trim()) {
      setError("Vui lòng nhập tên buổi học.");
      return;
    }

    if (formEndTime <= formStartTime) {
      setError("Giờ kết thúc phải sau giờ bắt đầu.");
      return;
    }

    const payload = {
      class_id: targetClassId,
      title: formTitle.trim(),
      date: formDate,
      start_time: formStartTime,
      end_time: formEndTime,
      room: formRoom.trim() || null,
      note: formNote.trim() || null,
    };

    setBusy(true);
    try {
      if (editingId) {
        await props.api(`/schedules/${editingId}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        setNotice(`Đã cập nhật lịch học #${editingId}.`);
        handleCancelEdit();
      } else {
        await props.api("/schedules", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        setNotice("Đã thêm lịch học mới thành công.");
        setFormTitle("");
        setFormRoom("");
        setFormNote("");
      }
      await loadSchedules();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg || "Lưu lịch học thất bại");
    } finally {
      setBusy(false);
    }
  };

  // Export handlers
  const handleExport = async (format: "csv" | "xlsx" | "ics") => {
    setError("");
    setNotice("");
    setBusy(true);
    try {
      const params = new URLSearchParams();
      params.set("format", format);
      if (classFilter) params.set("class_id", classFilter);
      if (dateFrom) params.set("date_from", dateFrom);
      if (dateTo) params.set("date_to", dateTo);

      const classLabel = currentSelectedClass ? currentSelectedClass.code : "tat_ca";
      const fallbackName = `lich_hoc_${classLabel}.${format}`;
      await downloadFile(rawApi, `/schedules/export?${params.toString()}`, fallbackName);
      setNotice(`Đã xuất tệp lịch học định dạng .${format.toUpperCase()}`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg || `Xuất lịch học định dạng .${format} thất bại`);
    } finally {
      setBusy(false);
    }
  };

  // Template download handler
  const handleDownloadTemplate = async (format: "csv" | "xlsx") => {
    setError("");
    setNotice("");
    setBusy(true);
    try {
      const fallbackName = `mau_lich_hoc.${format}`;
      await downloadFile(rawApi, `/schedules/import-template?format=${format}`, fallbackName);
      setNotice(`Đã tải tệp mẫu .${format.toUpperCase()}`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg || `Tải tệp mẫu .${format} thất bại`);
    } finally {
      setBusy(false);
    }
  };

  // File selection for import
  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    setError("");
    setNotice("");
    setImportResult(null);
    const file = e.target.files?.[0] || null;
    if (!file) {
      setImportFile(null);
      return;
    }
    const isIcs = file.name.toLowerCase().endsWith(".ics");
    if (isIcs && !classFilter) {
      setError("Tệp .ics cần chọn lớp");
      setImportFile(null);
      if (e.target) e.target.value = "";
      return;
    }
    setImportFile(file);
  };

  // Preview import
  const handlePreviewImport = async () => {
    if (!importFile) return;
    const isIcs = importFile.name.toLowerCase().endsWith(".ics");
    if (isIcs && !classFilter) {
      setError("Tệp .ics cần chọn lớp");
      return;
    }
    setError("");
    setNotice("");
    setBusy(true);
    try {
      const fields: Record<string, string> = {
        mode: "preview",
        on_conflict: onConflict,
      };
      if (classFilter) {
        fields.class_id = classFilter;
      }
      if (keywordFilter.trim()) {
        fields.keyword = keywordFilter.trim();
      }
      const res = (await uploadImport(rawApi, "/schedules/import", importFile, fields)) as ScheduleImportResult;
      setImportResult(res);
      if (res.errors && res.errors.length > 0) {
        setError(`Tệp có ${res.errors.length} lỗi kiểm tra. Vui lòng xem bảng lỗi bên dưới.`);
      } else {
        const filteredPart = (res.filtered_out ?? 0) > 0 ? ` · ${res.filtered_out} không khớp môn` : "";
        setNotice(
          `Xem trước thành công: ${res.valid_rows}/${res.total_rows} dòng hợp lệ (${res.created} tạo mới, ${res.updated} cập nhật, ${res.skipped} bỏ qua${filteredPart}).`
        );
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg || "Không thể xem trước tệp nhập");
    } finally {
      setBusy(false);
    }
  };

  // Commit import
  const handleCommitImport = async () => {
    if (!importFile) return;
    const isIcs = importFile.name.toLowerCase().endsWith(".ics");
    if (isIcs && !classFilter) {
      setError("Tệp .ics cần chọn lớp");
      return;
    }
    setError("");
    setNotice("");
    setBusy(true);
    try {
      const fields: Record<string, string> = {
        mode: "commit",
        on_conflict: onConflict,
      };
      if (classFilter) {
        fields.class_id = classFilter;
      }
      if (keywordFilter.trim()) {
        fields.keyword = keywordFilter.trim();
      }
      const res = (await uploadImport(rawApi, "/schedules/import", importFile, fields)) as ScheduleImportResult;
      setImportResult(res);
      if (res.errors && res.errors.length > 0) {
        setError(`Nhập thất bại: tệp còn ${res.errors.length} lỗi.`);
      } else {
        const filteredPart = (res.filtered_out ?? 0) > 0 ? ` · ${res.filtered_out} không khớp môn` : "";
        setNotice(`Đã nhập thành công: ${res.created} tạo mới, ${res.updated} cập nhật, ${res.skipped} bỏ qua${filteredPart}.`);
        setImportFile(null);
        setImportResult(null);
        if (importInputRef.current) importInputRef.current.value = "";
        await loadSchedules();
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg || "Lỗi khi nhập lịch học");
    } finally {
      setBusy(false);
    }
  };

  // Cancel preview
  const handleCancelPreview = () => {
    setImportFile(null);
    setImportResult(null);
    if (importInputRef.current) {
      importInputRef.current.value = "";
    }
  };

  return (
    <div>
      <p className="muted" style={{ margin: "0 0 16px 0", fontSize: "0.85rem" }}>
        Ca điểm danh tự mở lúc bắt đầu và tự đóng lúc kết thúc buổi học. Đóng ca thì sinh viên chưa điểm danh bị ghi vắng.
      </p>

      {/* Thông báo trạng thái */}
      {error && (
        <div className="error" style={{ marginBottom: "20px" }}>
          {error}
        </div>
      )}
      {notice && (
        <div className="message" style={{ marginBottom: "20px" }}>
          <span>{notice}</span>
          <button type="button" className="link" onClick={() => setNotice("")} style={{ cursor: "pointer" }}>
            ✕
          </button>
        </div>
      )}

      {/* 1. Bộ lọc lịch học */}
      <section className="panel" style={{ marginBottom: "24px" }}>
        <div className="panel-head">
          <h2>Bộ lọc lịch học</h2>
          <button type="button" className="secondary" disabled={busy} onClick={loadSchedules}>
            Làm mới
          </button>
        </div>
        <div className="inline-form" style={{ marginTop: "12px" }}>
          <label style={{ flex: "1 1 240px" }}>
            Lớp học
            <select
              value={classFilter}
              onChange={(e) => {
                setClassFilter(e.target.value);
                setImportResult(null);
              }}
              disabled={busy}
            >
              <option value="">Tất cả lớp học (chỉ xem)</option>
              {props.classes.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.code} · {c.name}
                </option>
              ))}
            </select>
          </label>

          <label style={{ flex: "1 1 160px" }}>
            Từ ngày
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              disabled={busy}
            />
          </label>

          <label style={{ flex: "1 1 160px" }}>
            Đến ngày
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              disabled={busy}
            />
          </label>

          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={() => {
              const d = getDefaultDateRange();
              setDateFrom(d.from);
              setDateTo(d.to);
            }}
            title="Đặt lại khoảng ngày từ thứ Hai tuần này đến hết 4 tuần sau"
          >
            4 tuần mặc định
          </button>
        </div>
      </section>

      {/* 2 cột: Form Thêm/Sửa & Khối Nhập/Xuất */}
      <div className="two-col" style={{ marginBottom: "24px" }}>
        {/* 2. Form thêm/sửa */}
        <section className="panel">
          <h2>{editingId ? "Sửa lịch học" : "Thêm lịch học mới"}</h2>

          <form onSubmit={handleFormSubmit}>
            <div style={{ marginBottom: "14px" }}>
              <small className="muted">
                {editingId ? (
                  <>
                    Đang sửa lịch học #{editingId} (Lớp: <strong>{editingClass?.code || "Chưa rõ"}</strong>)
                  </>
                ) : classFilter ? (
                  <>
                    Thêm lịch cho lớp: <strong>{currentSelectedClass?.code}</strong> ({currentSelectedClass?.name})
                  </>
                ) : (
                  <span style={{ color: "var(--warning)" }}>
                    ⚠️ Vui lòng chọn một lớp cụ thể ở bộ lọc phía trên để thêm lịch.
                  </span>
                )}
              </small>
            </div>

            <label>
              Tên buổi học *
              <input
                required
                maxLength={255}
                placeholder="Ví dụ: IoT và ứng dụng · Buổi 01"
                value={formTitle}
                onChange={(e) => setFormTitle(e.target.value)}
                disabled={busy}
              />
            </label>

            <label>
              Ngày học *
              <input
                type="date"
                required
                value={formDate}
                onChange={(e) => setFormDate(e.target.value)}
                disabled={busy}
              />
            </label>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
              <label style={{ margin: "8px 0" }}>
                Giờ bắt đầu *
                <input
                  type="time"
                  required
                  value={formStartTime}
                  onChange={(e) => setFormStartTime(e.target.value)}
                  disabled={busy}
                />
              </label>

              <label style={{ margin: "8px 0" }}>
                Giờ kết thúc *
                <input
                  type="time"
                  required
                  value={formEndTime}
                  onChange={(e) => setFormEndTime(e.target.value)}
                  disabled={busy}
                />
              </label>
            </div>

            <label>
              Phòng học
              <input
                maxLength={64}
                placeholder="Ví dụ: 402-A2"
                value={formRoom}
                onChange={(e) => setFormRoom(e.target.value)}
                disabled={busy}
              />
            </label>

            <label>
              Ghi chú
              <input
                maxLength={1000}
                placeholder="Ghi chú thêm về buổi học..."
                value={formNote}
                onChange={(e) => setFormNote(e.target.value)}
                disabled={busy}
              />
            </label>

            <div className="actions" style={{ marginTop: "18px" }}>
              <button
                type="submit"
                disabled={busy || (!editingId && !classFilter)}
                title={!editingId && !classFilter ? "Vui lòng chọn lớp học ở bộ lọc để thêm lịch" : undefined}
              >
                {editingId ? "Lưu thay đổi" : "Lưu lịch học"}
              </button>
              {editingId && (
                <button
                  type="button"
                  className="secondary"
                  disabled={busy}
                  onClick={handleCancelEdit}
                >
                  Hủy sửa
                </button>
              )}
            </div>
          </form>
        </section>

        {/* 4. Khối nhập/xuất */}
        <section className="panel">
          <h2>Nhập & Xuất lịch học</h2>

          {/* Xuất file */}
          <div style={{ marginBottom: "22px", paddingBottom: "18px", borderBottom: "1px solid var(--line)" }}>
            <h3 style={{ fontSize: "0.88rem", fontWeight: 700, margin: "0 0 8px 0" }}>Xuất dữ liệu lịch học</h3>
            <p className="muted" style={{ fontSize: "0.74rem", margin: "0 0 10px 0" }}>
              Xuất lịch theo bộ lọc hiện tại ({classFilter ? `Lớp ${currentSelectedClass?.code}` : "Tất cả lớp"}, {dateFrom} đến {dateTo}).
            </p>
            <div className="actions">
              <button type="button" className="secondary" disabled={busy} onClick={() => handleExport("csv")}>
                Xuất CSV
              </button>
              <button type="button" className="secondary" disabled={busy} onClick={() => handleExport("xlsx")}>
                Xuất Excel
              </button>
              <button type="button" className="secondary" disabled={busy} onClick={() => handleExport("ics")}>
                Xuất ICS
              </button>
            </div>
            <small className="muted" style={{ marginTop: "6px" }}>
              * Tệp ICS mở được bằng Google Calendar, Outlook.
            </small>
          </div>

          {/* Tải tệp mẫu */}
          <div style={{ marginBottom: "22px", paddingBottom: "18px", borderBottom: "1px solid var(--line)" }}>
            <h3 style={{ fontSize: "0.88rem", fontWeight: 700, margin: "0 0 8px 0" }}>Tệp mẫu nhập lịch</h3>
            <div className="actions">
              <button type="button" className="secondary" disabled={busy} onClick={() => handleDownloadTemplate("csv")}>
                Tải mẫu CSV
              </button>
              <button type="button" className="secondary" disabled={busy} onClick={() => handleDownloadTemplate("xlsx")}>
                Tải mẫu Excel
              </button>
            </div>
          </div>

          {/* Nhập tệp */}
          <div>
            <h3 style={{ fontSize: "0.88rem", fontWeight: 700, margin: "0 0 8px 0" }}>Nhập lịch từ tệp</h3>
            <p className="muted" style={{ fontSize: "0.74rem", margin: "0 0 10px 0" }}>
              Chấp nhận tệp .csv, .xlsx, .ics (tối đa 2 MiB, 2000 dòng). Tệp .ics bắt buộc chọn lớp ở bộ lọc.
            </p>

            <label style={{ margin: "10px 0" }}>
              Chọn tệp
              <input
                ref={importInputRef}
                type="file"
                accept=".csv,.xlsx,.ics,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/calendar"
                disabled={busy}
                onChange={handleFileChange}
              />
            </label>

            <label style={{ margin: "10px 0" }}>
              Lọc theo môn
              <input
                type="text"
                placeholder="VD: INT14149 hoặc IoT"
                maxLength={100}
                value={keywordFilter}
                onChange={(e) => setKeywordFilter(e.target.value)}
                disabled={busy}
              />
              <small className="muted" style={{ display: "block", marginTop: "4px" }}>
                File QLDT có lịch mọi môn. Nhập mã môn để chỉ lấy môn cần điểm danh.
              </small>
            </label>

            <label style={{ margin: "10px 0" }}>
              Xử lý khi trùng lịch học
              <select
                value={onConflict}
                onChange={(e) => setOnConflict(e.target.value as "skip" | "update")}
                disabled={busy}
              >
                <option value="skip">Bỏ qua lịch trùng (skip)</option>
                <option value="update">Cập nhật lịch trùng (update)</option>
              </select>
            </label>

            <div className="actions" style={{ marginTop: "14px" }}>
              <button
                type="button"
                disabled={busy || !importFile}
                onClick={handlePreviewImport}
              >
                Xem trước
              </button>
              {importResult && (
                <>
                  <button
                    type="button"
                    disabled={busy || importResult.errors.length > 0}
                    onClick={handleCommitImport}
                    title={importResult.errors.length > 0 ? "Tệp còn lỗi kiểm tra, không thể ghi vào hệ thống" : undefined}
                  >
                    Xác nhận nhập
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    disabled={busy}
                    onClick={handleCancelPreview}
                  >
                    Hủy xem trước
                  </button>
                </>
              )}
            </div>

            {/* Bảng xem trước và danh sách lỗi */}
            {importResult && (
              <div style={{ marginTop: "18px", borderTop: "1px dashed var(--line)", paddingTop: "14px" }}>
                <div style={{ fontSize: "0.76rem", lineHeight: "1.6", marginBottom: "12px" }}>
                  <strong>Kết quả {importResult.mode === "preview" ? "xem trước" : "nhập"}:</strong>{" "}
                  <span>
                    Tổng {importResult.total_rows} dòng · Hợp lệ {importResult.valid_rows} ·{" "}
                    Tạo mới {importResult.created} · Cập nhật {importResult.updated} · Bỏ qua {importResult.skipped}
                    {(importResult.filtered_out ?? 0) > 0 && ` · ${importResult.filtered_out} không khớp môn`}
                  </span>
                </div>

                {/* Danh sách lỗi */}
                {importResult.errors.length > 0 && (
                  <div style={{ marginBottom: "16px" }}>
                    <strong style={{ color: "var(--bad)", fontSize: "0.76rem" }}>
                      Có {importResult.errors.length} lỗi cần khắc phục:
                    </strong>
                    <div className="table-wrap" style={{ maxHeight: "200px", overflowY: "auto", marginTop: "6px" }}>
                      <table>
                        <thead>
                          <tr>
                            <th style={{ width: "50px" }}>Dòng</th>
                            <th style={{ width: "110px" }}>Trường</th>
                            <th>Lý do</th>
                          </tr>
                        </thead>
                        <tbody>
                          {importResult.errors.map((err, idx) => (
                            <tr key={idx}>
                              <td>
                                <strong>#{err.row}</strong>
                              </td>
                              <td>
                                <code>{err.field || "—"}</code>
                              </td>
                              <td style={{ color: "var(--bad)" }}>{err.message}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {/* Danh sách dòng dữ liệu xem trước */}
                {importResult.rows.length > 0 && (
                  <div>
                    <strong style={{ fontSize: "0.76rem" }}>
                      Dữ liệu chuẩn hóa ({importResult.rows.length} dòng):
                    </strong>
                    <div className="table-wrap" style={{ maxHeight: "240px", overflowY: "auto", marginTop: "6px" }}>
                      <table>
                        <thead>
                          <tr>
                            <th style={{ width: "45px" }}>#</th>
                            <th>Mã lớp</th>
                            <th>Tên buổi</th>
                            <th>Ngày</th>
                            <th>Giờ</th>
                            <th>Phòng</th>
                            <th>Hành động</th>
                          </tr>
                        </thead>
                        <tbody>
                          {importResult.rows.map((rowObj, idx) => {
                            const r = rowObj as PreviewRow;
                            return (
                              <tr key={idx}>
                                <td>#{r.row ?? idx + 1}</td>
                                <td>
                                  <strong>{r.class_code || "—"}</strong>
                                </td>
                                <td>{r.title || "—"}</td>
                                <td>{r.date || "—"}</td>
                                <td>
                                  {r.start_time && r.end_time ? `${r.start_time} - ${r.end_time}` : "—"}
                                </td>
                                <td>{r.room || "—"}</td>
                                <td>
                                  <span
                                    className={`badge ${
                                      r.action === "create"
                                        ? "open"
                                        : r.action === "update"
                                        ? "late"
                                        : r.action === "skip"
                                        ? ""
                                        : "offline"
                                    }`}
                                  >
                                    {r.action === "create"
                                      ? "Tạo mới"
                                      : r.action === "update"
                                      ? "Cập nhật"
                                      : r.action === "skip"
                                      ? "Bỏ qua"
                                      : r.action || "—"}
                                  </span>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </section>
      </div>

      {/* 3. Danh sách nhóm theo ngày */}
      <section className="panel spaced">
        <div className="panel-head">
          <h2>Danh sách lịch học</h2>
          <span className="muted" style={{ fontSize: "0.75rem" }}>
            Tổng cộng: <strong>{schedules.length}</strong> buổi học
          </span>
        </div>

        {groupedSchedules.length === 0 ? (
          <p className="empty">Không có lịch học nào trong khoảng thời gian đã chọn.</p>
        ) : (
          <div>
            {groupedSchedules.map(([dateStr, items]) => (
              <div key={dateStr} style={{ marginBottom: "26px" }}>
                <h3
                  style={{
                    fontSize: "0.95rem",
                    fontWeight: 700,
                    margin: "18px 0 10px 0",
                    color: "var(--accent)",
                    borderBottom: "2px solid #e1ebe3",
                    paddingBottom: "6px",
                  }}
                >
                  {formatDateHeader(dateStr)}
                </h3>

                <div className="list">
                  {items.map((s) => {
                    const isLocked = s.session_status === "open" || s.session_status === "closed";
                    const lockTitle = isLocked
                      ? "Buổi điểm danh đã mở hoặc đã đóng, không thể sửa/xóa lịch"
                      : undefined;

                    return (
                      <div className="list-row" key={s.id}>
                        <div>
                          <strong>
                            {s.start_time} - {s.end_time} · [{s.class_code}] {s.title}
                          </strong>
                          <small>
                            {s.room ? `Phòng: ${s.room}` : "Chưa xếp phòng"}
                            {s.note ? ` · ${s.note}` : ""}
                          </small>
                        </div>

                        <div className="actions">
                          {renderSessionBadge(s.session_status, s.session_id)}

                          <button
                            type="button"
                            className="secondary"
                            disabled={busy || isLocked}
                            title={lockTitle}
                            onClick={() => handleStartEdit(s)}
                          >
                            Sửa
                          </button>

                          <button
                            type="button"
                            className="danger"
                            disabled={busy || isLocked}
                            title={lockTitle}
                            onClick={() => handleDelete(s)}
                          >
                            Xóa
                          </button>

                          {s.session_id ? (
                            <button
                              type="button"
                              className="secondary"
                              disabled={busy}
                              onClick={() => props.onSessionCreated(s.session_id!)}
                            >
                              Xem buổi
                            </button>
                          ) : (
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => handleCreateSession(s.id)}
                            >
                              Tạo buổi điểm danh
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
