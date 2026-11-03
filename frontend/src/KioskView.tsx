import { useEffect, useState, useRef } from "react";
import {
  useCameraStream,
  computeContainOverlay,
  computeRoiOverlay,
  Preview,
} from "./useCameraStream";

type Device = { id: string; name: string; status: string };
type Student = { id: number; student_code: string; name: string; class_id: number | null; date_of_birth: string | null; enrolled: boolean };
type Classroom = { id: number; code: string; name: string };
type Attendance = { id: number; session_id?: number; student_id: number; student_code: string; student_name: string; checked_at: string; status: string; verification: string };
type Session = { id: number; class_id: number; title: string; status: string };

type Props = {
  api: (path: string, init?: RequestInit) => Promise<Response>;
  devices: Device[];
  selectedSession: string;
  onSelectSession?: (id: string) => void;
  token: string;
  apiUrl: string;
  students: Student[];
  classes?: Classroom[];
  rows: Attendance[];
  sessions: Session[];
};

export default function KioskView({ api, devices, selectedSession, onSelectSession, token, apiUrl, students, classes, rows, sessions }: Props) {
  const [camera, setCamera] = useState("");
  const [lastCheckin, setLastCheckin] = useState<{ student: Student; time: string; score?: number; created?: boolean } | null>(null);
  const [activeAlert, setActiveAlert] = useState<{ name: string; student_code: string; isNew: boolean; time: string } | null>(null);
  const alertTimerRef = useRef<number | null>(null);
  const effectiveCamera = devices.some(d => d.id === camera) ? camera : devices[0]?.id ?? "";
  const lastAcceptedRef = useRef<string>("");

  const studentsRef = useRef(students);
  studentsRef.current = students;
  const apiRef = useRef(api);
  apiRef.current = api;
  const audioCtxRef = useRef<AudioContext | null>(null);

  // Hook camera stream duy nhất quản lý WebSocket, canvas rendering và FPS
  const { canvasRef, meta, fps, connected: hasSource, canvasSize } =
    useCameraStream(effectiveCamera, token, apiUrl, false);

  // Lấy config 1 lần lúc mount hoặc đổi camera (fallback khi chưa có meta từ WS)
  const [fallbackConfig, setFallbackConfig] = useState<Preview["config"] | null>(null);
  useEffect(() => {
    if (!effectiveCamera) return;
    let cancelled = false;
    apiRef.current(`/devices/${encodeURIComponent(effectiveCamera)}/preview`)
      .then(r => r.json())
      .then((data: Preview) => {
        if (!cancelled && data.config) {
          setFallbackConfig(data.config);
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [effectiveCamera]);

  const preview: Preview | null = meta || (fallbackConfig ? ({ available: false, config: fallbackConfig } as Preview) : null);
  const roi = preview?.config;
  const result = preview?.result;

  // Khởi tạo và mở khóa AudioContext khi người dùng tương tác với trang
  const getAudioContext = () => {
    if (!audioCtxRef.current) {
      const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      if (AudioCtx) audioCtxRef.current = new AudioCtx();
    }
    if (audioCtxRef.current && audioCtxRef.current.state === "suspended") {
      audioCtxRef.current.resume().catch(() => {});
    }
    return audioCtxRef.current;
  };

  useEffect(() => {
    const unlock = () => { getAudioContext(); };
    window.addEventListener("click", unlock, { once: true });
    window.addEventListener("keydown", unlock, { once: true });
    return () => {
      window.removeEventListener("click", unlock);
      window.removeEventListener("keydown", unlock);
    };
  }, []);

  // Xác định phiên đang điểm danh: phiên chọn -> phiên đang mở -> phiên đầu tiên
  const currentSession = sessions.find(s => String(s.id) === selectedSession)
    || sessions.find(s => s.status === "open")
    || sessions[0];
  const currentSessionId = currentSession?.id;

  // Tự động gán phiên đang chọn cho camera khi mở chế độ Kiosk
  useEffect(() => {
    if (!effectiveCamera || !currentSessionId) return;
    void apiRef.current(`/devices/${encodeURIComponent(effectiveCamera)}/config`).then(r => r.json()).then(conf => {
      if (conf && conf.session_id !== currentSessionId) {
        void apiRef.current(`/devices/${encodeURIComponent(effectiveCamera)}/config`, {
          method: "PUT",
          body: JSON.stringify({ ...conf, session_id: currentSessionId })
        });
      }
    }).catch(() => {});
  }, [effectiveCamera, currentSessionId]);

  // Âm thanh BÍP tổng hợp chất lượng cao qua Web Audio API của trình duyệt
  const playChime = () => {
    try {
      const ctx = getAudioContext();
      if (!ctx) return;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(1200, ctx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(1800, ctx.currentTime + 0.12);
      gain.gain.setValueAtTime(0.3, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.25);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.26);
    } catch {
      // AudioContext policy fallback
    }
  };

  // Kích hoạt phản hồi khi nhận diện thành công qua meta đẩy từ WebSocket
  useEffect(() => {
    const res = preview?.result;
    if (res?.accepted && res.student_code) {
      const stu = studentsRef.current.find(s => s.student_code === res.student_code);
      const studentName = stu?.name || (res as { student_name?: string }).student_name || res.student_code;
      const isCreated = res.created !== false;

      if (res.student_code !== lastAcceptedRef.current) {
        lastAcceptedRef.current = res.student_code;
        const checkinTime = new Date().toLocaleTimeString("vi-VN");
        const fullStudent: Student = stu || {
          id: 0, student_code: res.student_code, name: studentName, class_id: null, date_of_birth: null, enrolled: true
        };
        setLastCheckin({
          student: fullStudent,
          time: checkinTime,
          score: res.pad_score,
          created: isCreated
        });

        if (isCreated) {
          playChime();
        }

        if (alertTimerRef.current) clearTimeout(alertTimerRef.current);
        setActiveAlert({
          name: studentName,
          student_code: res.student_code,
          isNew: isCreated,
          time: checkinTime
        });

        alertTimerRef.current = window.setTimeout(() => {
          setActiveAlert(null);
          lastAcceptedRef.current = "";
        }, 4000);
      }
    }
  }, [preview?.result]);

  useEffect(() => {
    return () => {
      if (alertTimerRef.current) clearTimeout(alertTimerRef.current);
    };
  }, []);

  // Lọc chính xác các lượt điểm danh thuộc phiên hiện tại
  const sessionRows = currentSessionId
    ? rows.filter(r => r.session_id === undefined || r.session_id === currentSessionId)
    : rows;

  // Khử trùng: Đếm số lượng sinh viên DUY NHẤT có mặt trong phiên này (tránh đếm lặp)
  const presentStudentIds = new Set(
    sessionRows
      .filter(r => r.status === "present" || r.status === "late")
      .map(r => r.student_id)
  );
  const presentCount = presentStudentIds.size;

  // Sĩ số thực tế của lớp thuộc phiên đang chọn
  const classStudents = currentSession
    ? students.filter(s => s.class_id === currentSession.class_id)
    : students;
  const totalCount = classStudents.length || students.length || 36;

  const effectiveDevice = devices.find(d => d.id === effectiveCamera);
  const deviceDisplayName = effectiveDevice ? effectiveDevice.name : effectiveCamera || "CAMERA";
  const studentClassName = classes?.find(c => c.id === (lastCheckin?.student.class_id ?? currentSession?.class_id))?.code || "D23CTAT01-B";

  // Tính toán khung mặt và ROI theo tỷ lệ contain không lệch khi resize
  const frameSize = result?.frame_size;
  const boxOverlay = computeContainOverlay(result?.box, frameSize, canvasSize.width, canvasSize.height);
  const roiOverlay = computeRoiOverlay(roi, frameSize, canvasSize.width, canvasSize.height);

  return (
    <div className="kiosk-container">
      <div className="kiosk-header">
        <div className="kiosk-title-block">
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 8 }}>
            <span className="kiosk-badge-school">HỌC VIỆN CÔNG NGHỆ BƯU CHÍNH VIỄN THÔNG (PTIT)</span>
            {currentSession && (
              <span className={`kiosk-session-badge ${currentSession.status}`}>
                {currentSession.status === "open" ? "● ĐANG MỞ ĐIỂM DANH" : "🔒 ĐÃ ĐÓNG PHIÊN"}
              </span>
            )}
            {onSelectSession && sessions.length > 1 && (
              <label style={{ margin: 0, display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 6, fontSize: "0.75rem", color: "#a8bbb2" }}>
                <span>Đổi buổi:</span>
                <select
                  className="kiosk-session-select"
                  value={selectedSession || String(currentSessionId || "")}
                  onChange={e => onSelectSession(e.target.value)}
                >
                  {sessions.map(s => (
                    <option key={s.id} value={s.id}>
                      #{s.id} {s.title} ({s.status === "open" ? "Đang mở" : "Đã đóng"})
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          <h1 className="kiosk-main-title">KIOSK ĐIỂM DANH SINH VIÊN</h1>
          <p className="kiosk-subtitle">
            Buổi học: <b>{currentSession?.title || "Điểm danh IoT"}</b> • Lớp: <b>{classes?.find(c => c.id === currentSession?.class_id)?.code || "D23CTAT01-B"}</b> • Nhóm: <b>05</b>
          </p>
        </div>
        <div className="kiosk-live-stats">
          <div className="kiosk-stat-card">
            <small>TỔNG SĨ SỐ</small>
            <strong>{totalCount}</strong>
          </div>
          <div className="kiosk-stat-card success">
            <small>ĐÃ CÓ MẶT</small>
            <strong>{presentCount}</strong>
          </div>
          <div className="kiosk-stat-card pending">
            <small>CHƯA ĐIỂM DANH</small>
            <strong>{Math.max(0, totalCount - presentCount)}</strong>
          </div>
        </div>
      </div>

      <div className="kiosk-body-grid">
        {/* KHUNG CAMERA CHÍNH */}
        <div className="kiosk-camera-card">
          <div className="kiosk-camera-topbar">
            <div className="kiosk-status-pill">
              <span className={`kiosk-dot ${hasSource ? "live" : "offline"}`}></span>
              <span>{hasSource ? `CAMERA ONLINE (${deviceDisplayName})` : "ĐANG CHỜ KẾT NỐI CAMERA"}</span>
            </div>
            <select
              value={effectiveCamera}
              onChange={e => setCamera(e.target.value)}
              className="kiosk-camera-select"
            >
              {devices.map(d => <option key={d.id} value={d.id}>{d.name} ({d.id})</option>)}
            </select>
          </div>

          <div className="kiosk-viewport">
            <div className="kiosk-image-wrapper" style={{ display: hasSource ? "block" : "none" }}>
              <canvas ref={canvasRef} style={{ width: "100%", height: "auto", display: "block" }} />
              {roiOverlay && (
                <div className="kiosk-roi-box" style={roiOverlay}>
                  <div className="roi-corner top-left"></div>
                  <div className="roi-corner top-right"></div>
                  <div className="roi-corner bottom-left"></div>
                  <div className="roi-corner bottom-right"></div>
                  <span className="roi-label">KHUNG NHẬN DIỆN</span>
                  <div className="roi-scanline"></div>
                </div>
              )}
              {/* Khung chữ nhật bám theo khuôn mặt nhận diện (Face Bounding Box) */}
              {boxOverlay && (
                <div
                  className={`kiosk-face-box ${result?.accepted ? "verified" : result?.reason?.includes("spoof") ? "spoof" : "scanning"}`}
                  style={boxOverlay}
                >
                  <span className="face-tag">{result?.student_code || (result?.accepted ? "HỢP LỆ" : "ĐANG QUÉT")}</span>
                </div>
              )}
              {hasSource && <span className="camera-fps-badge">{fps} FPS</span>}
              {/* Overlay thông báo điểm danh */}
              {activeAlert && (
                <div className="kiosk-success-flash">
                  <div className={`kiosk-success-banner ${activeAlert.isNew ? "new" : "existing"}`}>
                    <span className="check-icon">✓</span>
                    <div>
                      <h3>{activeAlert.isNew ? "ĐIỂM DANH THÀNH CÔNG" : "ĐÃ GHI NHẬN CÓ MẶT"}</h3>
                      <p className="student-highlight">{activeAlert.name}</p>
                      <span className="student-subcode">{activeAlert.student_code}</span>
                    </div>
                  </div>
                </div>
              )}
            </div>
            {!hasSource && (
              <div className="kiosk-empty-view">
                <div className="kiosk-spinner"></div>
                <p>Đang chờ kết nối camera...</p>
              </div>
            )}
          </div>

          <div className="kiosk-instruction-bar">
            <span className="kiosk-instruction-icon">ℹ</span>
            <span>
              {activeAlert
                ? (activeAlert.isNew
                    ? `Điểm danh thành công: Sinh viên ${activeAlert.name} (${activeAlert.student_code}).`
                    : `Sinh viên ${activeAlert.name} (${activeAlert.student_code}) đã có mặt trong buổi học.`)
                : result?.reason && result.reason !== "ok"
                  ? (result.reason.includes("spoof")
                      ? "Cảnh báo: Không thể xác thực khuôn mặt trực tiếp."
                      : result.reason.includes("no face") || result.reason.includes("waiting")
                        ? "Vui lòng nhìn thẳng vào camera trong khung nhận diện."
                        : `Trạng thái: ${result.reason}`)
                  : "Vui lòng nhìn thẳng vào camera để điểm danh."}
            </span>
          </div>
        </div>

        {/* CỘT THÔNG TIN PHẢN HỒI SINH VIÊN */}
        <div className="kiosk-sidebar-card">
          <h2 className="kiosk-section-title">KẾT QUẢ ĐIỂM DANH</h2>

          {lastCheckin ? (
            <div className="kiosk-student-card animated">
              <div className="kiosk-card-header">
                <div className="kiosk-avatar-placeholder">
                  {lastCheckin.student.name.charAt(0)}
                </div>
                <div>
                  <span className={lastCheckin.created === false ? "kiosk-badge-info" : "kiosk-badge-success"}>
                    {lastCheckin.created === false ? "✓ ĐÃ CÓ MẶT" : "✓ ĐIỂM DANH THÀNH CÔNG"}
                  </span>
                  <h3 className="kiosk-student-name">{lastCheckin.student.name}</h3>
                  <span className="kiosk-student-id">{lastCheckin.student.student_code}</span>
                </div>
              </div>

              <div className="kiosk-card-details">
                <div className="detail-row">
                  <span>Buổi học:</span>
                  <b>{currentSession?.title || "Điểm danh IoT"}</b>
                </div>
                <div className="detail-row">
                  <span>Lớp sinh hoạt:</span>
                  <b>{studentClassName}</b>
                </div>
                <div className="detail-row">
                  <span>Thời gian:</span>
                  <b>{lastCheckin.time}</b>
                </div>
                <div className="detail-row">
                  <span>Trạng thái:</span>
                  <b className="verified-text">Hợp lệ</b>
                </div>
              </div>
            </div>
          ) : (
            <div className="kiosk-waiting-card">
              <div className="radar-icon">◎</div>
              <p>Sẵn sàng nhận diện sinh viên tiếp theo</p>
            </div>
          )}

          <div className="kiosk-recent-list">
            <h3>Danh sách có mặt gần nhất</h3>
            <div className="kiosk-recent-table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Thời gian</th>
                    <th>Mã SV</th>
                    <th>Họ và Tên</th>
                    <th>Trạng thái</th>
                  </tr>
                </thead>
                <tbody>
                  {sessionRows.slice(0, 8).map(r => (
                    <tr key={r.id}>
                      <td>{new Date(r.checked_at).toLocaleTimeString("vi-VN")}</td>
                      <td><b>{r.student_code}</b></td>
                      <td>{r.student_name}</td>
                      <td>
                        <span className={`badge ${r.status}`}>
                          {r.status === "late" ? "Đi muộn" : "Có mặt"}
                        </span>
                      </td>
                    </tr>
                  ))}
                  {!sessionRows.length && (
                    <tr>
                      <td colSpan={4} className="empty">Chưa có lượt điểm danh nào trong phiên.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
