import { useEffect, useState, useCallback } from "react";
import type { ApiFn } from "./fileTransfer";

export interface AuditLogEntry {
  id: number;
  actor: string;
  action: string;
  target: string | null;
  detail: unknown;
  ip_address: string | null;
  created_at: string;
}

const PAGE_SIZE = 100;

const ACTION_LABELS: Record<string, string> = {
  "auth.login": "Đăng nhập",
  "auth.login_failed": "Đăng nhập sai",
  "auth.login_locked": "Bị khóa đăng nhập",
  "auth.logout": "Đăng xuất",
  "students.import": "Nhập sinh viên",
  "students.export": "Xuất sinh viên",
  "schedules.create": "Tạo lịch học",
  "schedules.update": "Cập nhật lịch học",
  "schedules.delete": "Xóa lịch học",
  "schedules.create_session": "Tạo buổi điểm danh",
  "schedules.import": "Nhập lịch học",
  "schedules.export": "Xuất lịch học",
};

function formatTime(value: string): string {
  if (!value) return "—";
  const dateStr = /Z$|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`;
  const date = new Date(dateStr);
  return isNaN(date.getTime()) ? value : date.toLocaleString("vi-VN");
}

function formatDetail(detail: unknown): { shortText: string; fullText: string } {
  if (detail === null || detail === undefined) {
    return { shortText: "—", fullText: "" };
  }
  let fullText: string;
  if (typeof detail === "string") {
    fullText = detail;
  } else {
    try {
      fullText = JSON.stringify(detail);
    } catch {
      fullText = String(detail);
    }
  }
  if (!fullText) {
    return { shortText: "—", fullText: "" };
  }
  const shortText = fullText.length > 120 ? fullText.slice(0, 120) + "…" : fullText;
  return { shortText, fullText };
}

export default function AuditPanel(props: { api: ApiFn }) {
  const { api } = props;
  const [logs, setLogs] = useState<AuditLogEntry[]>([]);
  const [filter, setFilter] = useState<string>("");
  const [offset, setOffset] = useState<number>(0);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string>("");

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      params.set("limit", String(PAGE_SIZE));
      params.set("offset", String(offset));
      if (filter) {
        params.set("action", filter);
      }

      const res = await api(`/audit-logs?${params.toString()}`);
      if (!res.ok) {
        let errorMsg = `Yêu cầu thất bại (${res.status})`;
        try {
          const body = (await res.json()) as { detail?: unknown };
          if (typeof body.detail === "string") {
            errorMsg = body.detail;
          }
        } catch {
          // Bỏ qua lỗi parse JSON nếu body không phải JSON
        }
        throw new Error(errorMsg);
      }

      const data = (await res.json()) as AuditLogEntry[];
      setLogs(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không thể tải nhật ký quản trị");
    } finally {
      setLoading(false);
    }
  }, [api, filter, offset]);

  useEffect(() => {
    void fetchLogs();
  }, [fetchLogs]);

  return (
    <section className="panel spaced">
      <div className="panel-head">
        <h2>Nhật ký quản trị</h2>
        <div className="actions">
          <select
            aria-label="Lọc nhật ký"
            value={filter}
            onChange={(e) => {
              setFilter(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">Tất cả</option>
            <option value="auth.">Đăng nhập (auth.)</option>
            <option value="students.">Sinh viên (students.)</option>
            <option value="schedules.">Lịch học (schedules.)</option>
          </select>
          <button type="button" onClick={() => void fetchLogs()} disabled={loading}>
            {loading ? "Đang tải..." : "Làm mới"}
          </button>
        </div>
      </div>

      {error && <p className="error">{error}</p>}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Thời gian</th>
              <th>Người thao tác</th>
              <th>Hành động</th>
              <th>Đối tượng</th>
              <th>IP</th>
              <th>Chi tiết</th>
            </tr>
          </thead>
          <tbody>
            {logs.map((log) => {
              const isWarning =
                log.action === "auth.login_failed" || log.action === "auth.login_locked";
              const { shortText, fullText } = formatDetail(log.detail);

              return (
                <tr key={log.id} className={isWarning ? "danger" : undefined}>
                  <td>{formatTime(log.created_at)}</td>
                  <td>
                    <strong>{log.actor}</strong>
                  </td>
                  <td>
                    <span className={isWarning ? "badge error" : "badge"}>
                      {ACTION_LABELS[log.action] || log.action}
                    </span>
                  </td>
                  <td>{log.target || "—"}</td>
                  <td>{log.ip_address || "—"}</td>
                  <td title={fullText || undefined}>
                    <code>{shortText}</code>
                  </td>
                </tr>
              );
            })}
            {!logs.length && !loading && (
              <tr>
                <td colSpan={6} className="empty">
                  Chưa có bản ghi nhật ký nào.
                </td>
              </tr>
            )}
            {loading && !logs.length && (
              <tr>
                <td colSpan={6} className="empty">
                  Đang tải dữ liệu...
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="toolbar" style={{ marginTop: 18, justifyContent: "space-between" }}>
        <div className="actions">
          <button
            type="button"
            className="secondary"
            onClick={() => setOffset((prev) => Math.max(0, prev - PAGE_SIZE))}
            disabled={offset === 0 || loading}
          >
            Trang trước
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => setOffset((prev) => prev + PAGE_SIZE)}
            disabled={logs.length < PAGE_SIZE || loading}
          >
            Trang sau
          </button>
        </div>
        <span className="muted">
          Dòng {logs.length > 0 ? offset + 1 : 0} – {offset + logs.length} (Trang{" "}
          {Math.floor(offset / PAGE_SIZE) + 1})
        </span>
      </div>
    </section>
  );
}
