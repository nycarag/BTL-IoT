import { useEffect, useState, useRef } from "react";

type Device = { id: string; name: string; status: string };
type Student = { id: number; student_code: string; name: string; class_id: number | null; date_of_birth: string | null; enrolled: boolean };
type Attendance = { id: number; student_id: number; student_code: string; student_name: string; checked_at: string; status: string; verification: string };
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
  token: string;
  apiUrl: string;
  students: Student[];
  rows: Attendance[];
  sessions: Session[];
};

export default function KioskView({ api, devices, selectedSession, token, apiUrl, students, rows, sessions }: Props) {
  const [camera, setCamera] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [source, setSource] = useState("");
  const [error, setError] = useState("");
  const [lastCheckin, setLastCheckin] = useState<{ student: Student; time: string; score?: number; created?: boolean } | null>(null);
  const effectiveCamera = devices.some(d => d.id === camera) ? camera : devices[0]?.id ?? "";
  const lastAcceptedRef = useRef<string>("");

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

  // Tự động gán phiên đang chọn cho camera khi mở chế độ Kiosk
  useEffect(() => {
    if (!effectiveCamera || !selectedSession) return;
    const sId = Number(selectedSession);
    if (!sId) return;
    void apiRef.current(`/devices/${encodeURIComponent(effectiveCamera)}/config`).then(r => r.json()).then(conf => {
      if (conf && conf.session_id !== sId) {
        void apiRef.current(`/devices/${encodeURIComponent(effectiveCamera)}/config`, {
          method: "PUT",
          body: JSON.stringify({ ...conf, session_id: sId })
        });
      }
    }).catch(() => {});
  }, [effectiveCamera, selectedSession]);

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
    const release = () => { if (objectUrl) URL.revokeObjectURL(objectUrl); objectUrl = ""; };

    const connect = () => {
      const url = new URL(`/ws/devices/${encodeURIComponent(effectiveCamera)}/camera`, apiUrl || window.location.origin);
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(url); socket.binaryType = "blob";
      socket.onopen = () => socket.send(JSON.stringify({ token }));
      socket.onmessage = async event => {
        if (typeof event.data === "string") {
          // Nhịp tim/giữ kết nối từ backend: Giữ nguyên khung hình hiện tại, KHÔNG xóa source gây chớp giật
          return;
        }
        const currentSocket = socket;
        const nextUrl = URL.createObjectURL(event.data);
        const image = new Image(); image.src = nextUrl;
        try {
          await image.decode();
          if (stopped || currentSocket !== socket) { URL.revokeObjectURL(nextUrl); return; }
          const oldUrl = objectUrl; objectUrl = nextUrl; setSource(nextUrl); setError(""); lastImage = Date.now();
          requestAnimationFrame(() => {
            if (oldUrl) URL.revokeObjectURL(oldUrl);
            if (!stopped && currentSocket.readyState === WebSocket.OPEN) currentSocket.send("next");
          });
        } catch {
          URL.revokeObjectURL(nextUrl);
          if (!stopped && currentSocket.readyState === WebSocket.OPEN) currentSocket.send("next");
        }
      };
      socket.onclose = event => {
        if (stopped) return;
        // Giữ lại khung hình gần nhất trên màn hình, không xóa source gây giật màn hình
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
            setSource("");
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
  const currentSession = sessions.find(s => String(s.id) === selectedSession) || sessions[0];
  const presentCount = rows.filter(r => r.status === "present" || r.status === "late").length;
  const totalCount = students.length || 36;

  return (
    <div className="kiosk-container">
      <div className="kiosk-header">
        <div className="kiosk-title-block">
          <span className="kiosk-badge-school">HỌC VIỆN CÔNG NGHỆ BƯU CHÍNH VIỄN THÔNG (PTIT)</span>
          <h1 className="kiosk-main-title">KIOSK ĐIỂM DANH SINH VIÊN THỜI GIAN THỰC</h1>
          <p className="kiosk-subtitle">
            Học phần: <b>IoT và ứng dụng (INT14149)</b> • Lớp: <b>D23CTAT01-B</b> • Nhóm: <b>05</b>
          </p>
        </div>
        <div className="kiosk-live-stats">
          <div className="kiosk-stat-card">
            <small>TỔNG SĨ SỐ</small>
            <strong>{totalCount}</strong>
          </div>
          <div className="kiosk-stat-card success">
            <small>ĐÃ ĐIỂM DANH</small>
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
              <span className={`kiosk-dot ${source ? "live" : "offline"}`}></span>
              <span>{source ? "CAMERA ONLINE (ESP32-CAM)" : "ĐANG CHỜ KẾT NỐI CAMERA"}</span>
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
            {source ? (
              <div className="kiosk-image-wrapper">
                <img src={source} alt="Stream Kiosk" />
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
            ) : (
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
                  <span className="kiosk-badge-success" style={lastCheckin.created === false ? { background: "#2563eb" } : undefined}>
                    {lastCheckin.created === false ? "✓ ĐÃ ĐIỂM DANH TRƯỚC ĐÓ" : "✓ CÓ MẶT THÀNH CÔNG"}
                  </span>
                  <h3 className="kiosk-student-name">{lastCheckin.student.name}</h3>
                  <span className="kiosk-student-id">{lastCheckin.student.student_code}</span>
                </div>
              </div>

              <div className="kiosk-card-details">
                <div className="detail-row">
                  <span>Lớp tín chỉ:</span>
                  <b>INT14149-20261-CT02</b>
                </div>
                <div className="detail-row">
                  <span>Lớp sinh hoạt:</span>
                  <b>D23CTAT01-B</b>
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
            <h3>Danh sách điểm danh gần nhất</h3>
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
                  {rows.slice(0, 8).map(r => (
                    <tr key={r.id}>
                      <td>{new Date(r.checked_at).toLocaleTimeString("vi-VN")}</td>
                      <td><b>{r.student_code}</b></td>
                      <td>{r.student_name}</td>
                      <td><span className="badge present">Có mặt</span></td>
                    </tr>
                  ))}
                  {!rows.length && (
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
