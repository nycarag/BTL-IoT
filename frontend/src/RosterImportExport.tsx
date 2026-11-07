import { useState, useRef, ChangeEvent } from "react";
import {
  type ApiFn,
  type ImportResult,
  downloadFile,
  makeRawApi,
  uploadImport,
} from "./fileTransfer";

interface Classroom {
  id: number;
  code: string;
  name: string;
}

interface RosterImportExportProps {
  api: ApiFn;
  apiUrl: string;
  token: string;
  classes: Classroom[];
  onImported: () => void;
}

function renderActionBadge(action: string) {
  switch (action) {
    case "create":
      return <span className="badge open">Thêm</span>;
    case "update":
      return <span className="badge late">Cập nhật</span>;
    case "skip":
      return <span className="badge">Bỏ qua</span>;
    case "error":
      return <span className="badge error">Lỗi</span>;
    default:
      return <span className="badge">{action}</span>;
  }
}

export default function RosterImportExport({
  api,
  apiUrl,
  token,
  classes,
  onImported,
}: RosterImportExportProps) {
  const [exportClassId, setExportClassId] = useState("");
  const [onConflict, setOnConflict] = useState<"skip" | "update">("skip");
  const [createMissingClasses, setCreateMissingClasses] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewResult, setPreviewResult] = useState<ImportResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleExport = async (format: "csv" | "xlsx") => {
    try {
      setBusy(true);
      setError("");
      setNotice("");
      const classParam = exportClassId ? `&class_id=${encodeURIComponent(exportClassId)}` : "";
      const path = `/students/export?format=${format}${classParam}`;
      const ext = format === "csv" ? "csv" : "xlsx";
      const fallback = `sinh_vien_${exportClassId ? "lop" : "tat_ca"}.${ext}`;
      await downloadFile(api, path, fallback);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Xuất tệp thất bại");
    } finally {
      setBusy(false);
    }
  };

  const handleDownloadTemplate = async () => {
    try {
      setBusy(true);
      setError("");
      setNotice("");
      await downloadFile(api, "/students/import-template?format=xlsx", "mau_nhap_sinh_vien.xlsx");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Tải tệp mẫu thất bại");
    } finally {
      setBusy(false);
    }
  };

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] || null;
    setSelectedFile(file);
    setPreviewResult(null);
    setError("");
    setNotice("");
  };

  const handleConflictChange = (e: ChangeEvent<HTMLSelectElement>) => {
    setOnConflict(e.target.value as "skip" | "update");
    setPreviewResult(null);
  };

  const handleMissingClassesChange = (e: ChangeEvent<HTMLInputElement>) => {
    setCreateMissingClasses(e.target.checked);
    setPreviewResult(null);
  };

  const handlePreview = async () => {
    if (!selectedFile) return;
    try {
      setBusy(true);
      setError("");
      setNotice("");
      const rawApi = makeRawApi(apiUrl, token);
      const res = await uploadImport(rawApi, "/students/import", selectedFile, {
        mode: "preview",
        on_conflict: onConflict,
        create_missing_classes: String(createMissingClasses),
      });
      setPreviewResult(res);
      if (res.errors && res.errors.length > 0) {
        setError(`Tệp có ${res.errors.length} lỗi cần xử lý trước khi nhập.`);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Kiểm tra tệp thất bại");
      setPreviewResult(null);
    } finally {
      setBusy(false);
    }
  };

  const canCommit = Boolean(
    previewResult &&
      previewResult.errors.length === 0 &&
      previewResult.created + previewResult.updated > 0
  );

  const handleCommit = async () => {
    if (!selectedFile || !previewResult) return;
    const count = previewResult.created + previewResult.updated;
    if (!window.confirm(`Nhập ${count} sinh viên vào hệ thống?`)) return;

    try {
      setBusy(true);
      setError("");
      setNotice("");
      const rawApi = makeRawApi(apiUrl, token);
      const res = await uploadImport(rawApi, "/students/import", selectedFile, {
        mode: "commit",
        on_conflict: onConflict,
        create_missing_classes: String(createMissingClasses),
      });

      if (res.errors && res.errors.length > 0) {
        setPreviewResult(res);
        setError("Quá trình nhập phát hiện lỗi, không có dữ liệu nào được ghi.");
        return;
      }

      setNotice(
        `Nhập thành công: ${res.created} thêm mới, ${res.updated} cập nhật, ${res.skipped} bỏ qua.`
      );
      setSelectedFile(null);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      setPreviewResult(null);
      onImported();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Nhập dữ liệu thất bại");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel">
      <h2>Nhập / xuất danh sách sinh viên</h2>

      {error && (
        <div className="message error" role="alert">
          <span>{error}</span>
          <button type="button" className="link" onClick={() => setError("")}>
            Đóng
          </button>
        </div>
      )}

      {notice && (
        <div className="message" role="status">
          <span>{notice}</span>
          <button type="button" className="link" onClick={() => setNotice("")}>
            Đóng
          </button>
        </div>
      )}

      <div style={{ marginBottom: "24px" }}>
        <h3 style={{ fontSize: "0.88rem", marginBottom: "12px" }}>Xuất danh sách sinh viên</h3>
        <div className="inline-form">
          <label style={{ margin: "0", minWidth: "200px" }}>
            Lớp học
            <select
              value={exportClassId}
              onChange={(e) => setExportClassId(e.target.value)}
              disabled={busy}
            >
              <option value="">Tất cả lớp</option>
              {classes.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.code} · {c.name}
                </option>
              ))}
            </select>
          </label>
          <button type="button" disabled={busy} onClick={() => void handleExport("csv")}>
            Xuất CSV
          </button>
          <button type="button" disabled={busy} onClick={() => void handleExport("xlsx")}>
            Xuất Excel
          </button>
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={() => void handleDownloadTemplate()}
          >
            Tải tệp mẫu (Excel)
          </button>
        </div>
      </div>

      <hr style={{ border: 0, borderTop: "1px solid var(--line)", margin: "20px 0" }} />

      <div>
        <h3 style={{ fontSize: "0.88rem", marginBottom: "12px" }}>Nhập danh sách sinh viên</h3>
        <div className="inline-form">
          <label style={{ margin: "0", minWidth: "220px" }}>
            Chọn tệp (.csv, .xlsx, .json)
            <input
              type="file"
              accept=".csv,.xlsx,.json"
              ref={fileInputRef}
              onChange={handleFileChange}
              disabled={busy}
            />
          </label>

          <label style={{ margin: "0", minWidth: "180px" }}>
            Nếu mã SV đã có
            <select value={onConflict} onChange={handleConflictChange} disabled={busy}>
              <option value="skip">Bỏ qua (skip)</option>
              <option value="update">Cập nhật (update)</option>
            </select>
          </label>

          <label className="check" style={{ margin: "0 0 10px 0", alignSelf: "flex-end" }}>
            <input
              type="checkbox"
              checked={createMissingClasses}
              onChange={handleMissingClassesChange}
              disabled={busy}
            />
            <span>Tự tạo lớp chưa có</span>
          </label>

          <button
            type="button"
            className="secondary"
            disabled={busy || !selectedFile}
            onClick={() => void handlePreview()}
          >
            Kiểm tra tệp
          </button>

          {previewResult && (
            <button
              type="button"
              disabled={busy || !canCommit}
              onClick={() => void handleCommit()}
            >
              Nhập vào hệ thống
            </button>
          )}
        </div>
      </div>

      {previewResult && (
        <div className="spaced">
          <div
            style={{
              padding: "12px 16px",
              background: previewResult.errors.length > 0 ? "#fff0ef" : "#e8f0e5",
              borderRadius: "8px",
              fontSize: "0.82rem",
              fontWeight: 600,
            }}
          >
            {previewResult.total_rows} dòng · {previewResult.created} thêm mới ·{" "}
            {previewResult.updated} cập nhật · {previewResult.skipped} bỏ qua ·{" "}
            {previewResult.errors.length} lỗi
          </div>

          {previewResult.errors.length > 0 && (
            <div className="table-wrap spaced">
              <h4 style={{ color: "var(--bad)", margin: "0 0 10px 0", fontSize: "0.85rem" }}>
                Danh sách lỗi ({previewResult.errors.length})
              </h4>
              <table>
                <thead>
                  <tr>
                    <th>Dòng</th>
                    <th>Cột</th>
                    <th>Nội dung</th>
                  </tr>
                </thead>
                <tbody>
                  {previewResult.errors.slice(0, 100).map((err, idx) => (
                    <tr key={idx}>
                      <td>
                        <strong>{err.row}</strong>
                      </td>
                      <td>{err.field || "—"}</td>
                      <td className="error">{err.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {previewResult.errors.length > 100 && (
                <p className="muted" style={{ marginTop: "8px" }}>
                  và {previewResult.errors.length - 100} lỗi khác
                </p>
              )}
            </div>
          )}

          {previewResult.rows.length > 0 && (
            <div className="table-wrap spaced">
              <h4 style={{ margin: "0 0 10px 0", fontSize: "0.85rem" }}>
                Xem trước dữ liệu ({Math.min(previewResult.rows.length, 50)} dòng đầu)
              </h4>
              <table>
                <thead>
                  <tr>
                    <th>Dòng</th>
                    <th>Mã SV</th>
                    <th>Họ và tên</th>
                    <th>Ngày sinh</th>
                    <th>Lớp</th>
                    <th>Thao tác</th>
                  </tr>
                </thead>
                <tbody>
                  {previewResult.rows.slice(0, 50).map((r, idx) => (
                    <tr key={idx}>
                      <td>{String(r.row ?? idx + 2)}</td>
                      <td>
                        <strong>{String(r.student_code ?? "")}</strong>
                      </td>
                      <td>{String(r.name ?? "")}</td>
                      <td>{String(r.date_of_birth ?? "—")}</td>
                      <td>{String(r.class_code ?? "—")}</td>
                      <td>{renderActionBadge(String(r.action ?? ""))}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
