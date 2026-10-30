import { useEffect, useState, useRef } from "react";

type Device = { id: string; name: string; status: string };
type Student = { id: number; student_code: string; name: string; class_id: number | null; date_of_birth: string | null; enrolled: boolean };
type Classroom = { id: number; code: string; name: string };
type Attendance = { id: number; session_id?: number; student_id: number; student_code: string; student_name: string; checked_at: string; status: string; verification: string };
type Session = { id: number; class_id: number; title: string; status: string };
type Preview = {
  available: boolean; received_at?: string; session_id?: number | null;
  config: { session_id: number | null; active: boolean; roi_left: number; roi_top: number; roi_right: number; roi_bottom: number };
  result?: { accepted?: boolean; created?: boolean; reason?: string; state?: string; student_code?: string; pad_score?: number; box?: number[]; frame_size?: number[] };
};

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
  const [preview, setPreview] = useState<Preview | null>(null);
  const [hasSource, setHasSource] = useState(false);
  const [error, setError] = useState("");
  const [lastCheckin, setLastCheckin] = useState<{ student: Student; time: string; score?: number; created?: boolean } | null>(null);
  const effectiveCamera = devices.some(d => d.id === camera) ? camera : devices[0]?.id ?? "";
  const lastAcceptedRef = useRef<string>("");
  const imgRef = useRef<HTMLImageElement>(null);

  const studentsRef = useRef(students);
  studentsRef.current = students;
  const apiRef = useRef(api);
  apiRef.current = api;
  const audioCtxRef = useRef<AudioContext | null>(null);

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

  useEffect(() => {
    if (!effectiveCamera) return;
    let stopped = false; let timer: number; let reconnect: number; let objectUrl = "";
    let socket: WebSocket; let lastImage = Date.now();
    const controller = new AbortController();
    const release = () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      objectUrl = "";
      if (imgRef.current) imgRef.current.src = "";
    };

    const connect = () => {
      const url = new URL(`/ws/devices/${encodeURIComponent(effectiveCamera)}/camera`, apiUrl || window.location.origin);
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(url); socket.binaryType = "blob";
      socket.onopen = () => socket.send(JSON.stringify({ token }));
      socket.onmessage = async event => {
        if (typeof event.data === "string") {
          return;
        }
        const currentSocket = socket;
        const nextUrl = URL.createObjectURL(event.data);
        const image = new Image(); image.src = nextUrl;
        try {
          await image.decode();
          if (stopped || currentSocket !== socket) {
            URL.revokeObjectURL(nextUrl);
            return;
          }
          const oldUrl = objectUrl;
          objectUrl = nextUrl;
          if (imgRef.current) {
            imgRef.current.src = nextUrl;
          }
          setHasSource(true);
          setError("");
          lastImage = Date.now();
          if (oldUrl) URL.revokeObjectURL(oldUrl);
          if (!stopped && currentSocket.readyState === WebSocket.OPEN) {
            currentSocket.send("next");
          }
        } catch {
          URL.revokeObjectURL(nextUrl);
          if (!stopped && currentSocket.readyState === WebSocket.OPEN) {
            currentSocket.send("next");
          }
        }
      };
      socket.onclose = event => {
        if (stopped) return;
        setError(event.code === 4401 ? "Phiên xem camera hết hạn — đăng nhập lại" : "Đang kết nối lại luồng camera…");
        if (event.code !== 4401) reconnect = window.setTimeout(connect, 1000);
      };
      socket.onerror = () => socket.close();
    };

    const update = async () => {
      try {
        const path = `/devices/${encodeURIComponent(effectiveCamera)}/preview`;
        const metadata: Preview = await (await apiRef.current(path, { signal: controller.signal, cache: "no-store" })).json();
        if (!stopped) {
          setPreview(metadata);
          // Chỉ xóa source khi camera mất tín hiệu hoàn toàn quá 15 giây
          if (Date.now() - lastImage > 15000 && !metadata.available) {
            release();
            setHasSource(false);
          }

          // Kích hoạt phản hồi khi nhận diện thành công
          const res = metadata?.result;
          if (res?.accepted && res.student_code && res.student_code !== lastAcceptedRef.current) {
            lastAcceptedRef.current = res.student_code;
            const stu = studentsRef.current.find(s => s.student_code === res.student_code) || {
              id: 0, student_code: res.student_code, name: res.student_code, class_id: null, date_of_birth: null, enrolled: true
            };
            setLastCheckin({
              student: stu,
              time: new Date().toLocaleTimeString("vi-VN"),
              score: res.pad_score,
              created: res.created !== false
            });
            playChime();
            setTimeout(() => { lastAcceptedRef.current = ""; }, 3000);
          }
        }
      } catch (e) {
        if (!stopped) {
          setError(e instanceof Error ? e.message : "Mất kết nối ảnh camera");
        }
      } finally { if (!stopped) timer = window.setTimeout(update, 600); }
    };

    connect(); void update();
    return () => { stopped = true; controller.abort(); clearTimeout(timer); clearTimeout(reconnect); socket?.close(); release(); };
  }, [effectiveCamera, token, apiUrl]);

  const roi = preview?.config;
  const result = preview?.result;

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
          <h1 className="kiosk-main-title">KIOSK ĐIỂM DANH SINH VIÊN THỜI GIAN THỰC</h1>
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
            <div className="kiosk-fas-badge">
              <span>🛡️ FAS: MiniFASNetV2 + ResNet-34 ACTIVE</span>
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
              <img ref={imgRef} alt="Stream Kiosk" />
              {roi && (
                <div
                  className="kiosk-roi-box"
                  style={{
                    left: `${roi.roi_left * 100}%`,
                    top: `${roi.roi_top * 100}%`,
                    width: `${(roi.roi_right - roi.roi_left) * 100}%`,
                    height: `${(roi.roi_bottom - roi.roi_top) * 100}%`
                  }}
                >
                  <div className="roi-corner top-left"></div>
                  <div className="roi-corner top-right"></div>
                  <div className="roi-corner bottom-left"></div>
                  <div className="roi-corner bottom-right"></div>
                  <span className="roi-label">VÙNG ĐIỂM DANH TRUNG TÂM</span>
                  <div className="roi-scanline"></div>
                </div>
              )}
              {/* Khung chữ nhật bám theo khuôn mặt nhận diện (Face Bounding Box) */}
              {result?.box && result?.frame_size && (
                <div
                  className={`kiosk-face-box ${result.accepted ? "verified" : result.reason?.includes("spoof") ? "spoof" : "scanning"}`}
                  style={{
                    left: `${(result.box[0] / result.frame_size[0]) * 100}%`,
                    top: `${(result.box[1] / result.frame_size[1]) * 100}%`,
                    width: `${(result.box[2] / result.frame_size[0]) * 100}%`,
                    height: `${(result.box[3] / result.frame_size[1]) * 100}%`,
                  }}
                >
                  <span className="face-tag">{result.student_code || (result.accepted ? "XÁC THỰC" : "NHẬN DIỆN")}</span>
                </div>
              )}
              {/* Overlay khi nhận diện thành công */}
              {result?.accepted && (
                <div className="kiosk-success-flash">
                  <div className="kiosk-success-banner" style={result.created === false ? { background: "rgba(37, 99, 235, 0.95)" } : undefined}>
                    <span className="check-icon">✓</span>
                    <div>
                      <h3>{result.created === false ? "ĐÃ ĐIỂM DANH TRƯỚC ĐÓ" : "XÁC THỰC THÀNH CÔNG"}</h3>
                      <p>{result.student_code}</p>
                    </div>
                  </div>
                </div>
              )}
            </div>
            {!hasSource && (
              <div className="kiosk-empty-view">
                <div className="kiosk-spinner"></div>
                <p>Đang kết nối luồng camera từ ESP32-CAM / Webcam...</p>
                <small>Chạy lệnh: python3 camera_bridge.py trên máy tính</small>
              </div>
            )}
          </div>

          <div className="kiosk-instruction-bar">
            <span className="kiosk-instruction-icon">ℹ</span>
            <span>
              {result?.accepted
                ? (result.created === false
                    ? `Sinh viên ${result.student_code} đã điểm danh trước đó trong phiên này (Có mặt).`
                    : `Điểm danh thành công: Sinh viên ${result.student_code}.`)
                : result?.reason
                  ? (result.reason.includes("spoof")
                      ? `Phát hiện nghi vấn giả mạo (Anti-Spoof từ chối)${result.pad_score !== undefined ? ` • Điểm tin cậy: ${(result.pad_score * 100).toFixed(1)}%` : ""}`
                      : result.reason.includes("no face")
                        ? "Đang tìm khuôn mặt trong vùng trung tâm ROI..."
                        : `Trạng thái: ${result.reason}`)
                  : "Hướng dẫn: Sinh viên bước vào vùng ROI trung tâm, mở mắt nhìn thẳng camera để xác thực."}
            </span>
          </div>
        </div>

        {/* CỘT THÔNG TIN PHẢN HỒI SINH VIÊN */}
        <div className="kiosk-sidebar-card">
          <h2 className="kiosk-section-title">KẾT QUẢ ĐIỂM DANH VỪA GHI NHẬN</h2>

          {lastCheckin ? (
            <div className="kiosk-student-card animated">
              <div className="kiosk-card-header">
                <div className="kiosk-avatar-placeholder">
                  {lastCheckin.student.name.charAt(0)}
                </div>
                <div>
                  <span className={lastCheckin.created === false ? "kiosk-badge-warning" : "kiosk-badge-success"}>
                    {lastCheckin.created === false ? "✓ ĐÃ ĐIỂM DANH TRƯỚC ĐÓ" : "✓ CÓ MẶT THÀNH CÔNG"}
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
                  <span>Thời gian điểm danh:</span>
                  <b>{lastCheckin.time}</b>
                </div>
                <div className="detail-row">
                  <span>Xác thực Anti-Spoof:</span>
                  <b className="verified-text">MiniFASNetV2 (Hợp lệ)</b>
                </div>
              </div>
            </div>
          ) : (
            <div className="kiosk-waiting-card">
              <div className="radar-icon">◎</div>
              <p>Sẵn sàng nhận diện sinh viên tiếp theo</p>
              <small>Hệ thống tự động đối chiếu vector 128D và kiểm tra chống giả mạo Deep Learning.</small>
            </div>
          )}

          <div className="kiosk-recent-list">
            <h3>Danh sách điểm danh gần nhất (Phiên hiện tại)</h3>
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
