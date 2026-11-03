import { useState } from "react";
import {
  useCameraStream,
  computeContainOverlay,
  computeRoiOverlay,
  Preview,
} from "./useCameraStream";

type Device = { id: string; name: string; status: string };
type Props = {
  api: (path: string, init?: RequestInit) => Promise<Response>;
  devices: Device[];
  selectedSession: string;
  token: string;
  apiUrl: string;
};

const reasons: Record<string, string> = {
  "waiting for stable face": "Giữ khuôn mặt ổn định trong vùng điểm danh",
  "no face detected": "Chưa phát hiện khuôn mặt",
  "face outside ROI": "Khuôn mặt đang ngoài vùng điểm danh",
  "face too small": "Hãy đứng gần camera hơn",
  "image too blurry": "Ảnh mờ — nhìn thẳng và giữ yên",
  "multiple faces in ROI": "Chỉ một người đứng trong vùng điểm danh",
  "spoof or uncertain PAD score": "PAD từ chối hoặc chưa đủ tin cậy",
  "unknown, uncertain or unavailable identity": "Chưa nhận diện được — kiểm tra đăng ký khuôn mặt và trạng thái mô hình",
};

export default function CameraPanel({ api: _api, devices, selectedSession, token, apiUrl }: Props) {
  const [camera, setCamera] = useState("");
  const [paused, setPaused] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const effectiveCamera = devices.some(d => d.id === camera) ? camera : devices[0]?.id ?? "";

  // Stream hook duy nhất quản lý WebSocket, canvas rendering và FPS
  const { canvasRef, meta, fps, connected: hasSource, error: streamError, canvasSize } =
    useCameraStream(effectiveCamera, token, apiUrl, paused);

  const preview = meta;
  const result = preview?.result;
  const error = streamError;
  const wrongSession = Boolean(preview && (selectedSession ? Number(selectedSession) !== preview.config.session_id : false));
  const verified = hasSource && !wrongSession && preview?.config.active && preview.session_id === preview.config.session_id && result?.accepted === true && !paused;
  const title = paused ? "Đã tạm dừng xem trước" : !hasSource ? "Chưa có ảnh camera" : wrongSession ? "Camera đang xử lý buổi học khác" : verified ? result?.created === false ? "Đã có mặt trong buổi học" : "Điểm danh thành công" : result?.state === "processing" ? "Đang xử lý…" : result?.state === "preview" ? "Xem trước" : "Đang xác thực";
  const reason = result?.reason ? reasons[result.reason] ?? result.reason : "Đứng trong khung ROI và nhìn thẳng camera.";
  const roi = preview?.config;

  // Tính toán overlay theo tỷ lệ contain chuẩn xác không lệch khi resize
  const frameSize = result?.frame_size;
  const boxOverlay = computeContainOverlay(result?.box, frameSize, canvasSize.width, canvasSize.height);
  const roiOverlay = computeRoiOverlay(roi, frameSize, canvasSize.width, canvasSize.height);

  return <section className={`panel camera-panel${expanded ? " camera-expanded" : ""}`}>
    <div className="panel-head"><div><h2>Camera điểm danh</h2></div><div className="actions"><button className="secondary" onClick={() => setPaused(!paused)}>{paused ? "Tiếp tục" : "Tạm dừng"}</button><button className="secondary" onClick={() => setExpanded(!expanded)}>{expanded ? "Thu gọn" : "Phóng to"}</button></div></div>
    <label>Camera<select value={effectiveCamera} onChange={e => setCamera(e.target.value)} disabled={!devices.length}><option value="" disabled>Chưa có thiết bị</option>{devices.map(d => <option key={d.id} value={d.id}>{d.name} · {d.id}</option>)}</select></label>
    <div className="camera-layout">
      <div className="camera-view">
        <div className="camera-image-wrap" style={{ display: hasSource && !paused ? "block" : "none" }}>
          <canvas ref={canvasRef} style={{ width: "100%", height: "auto", display: "block" }} />
          {roiOverlay && (
            <div className="camera-roi" style={roiOverlay}>
              <span>VÙNG ĐIỂM DANH</span>
            </div>
          )}
          {boxOverlay && (
            <div className="camera-face" style={boxOverlay}>
              <span className="camera-face-label">{result?.student_code || "Khuôn mặt"}</span>
            </div>
          )}
          {hasSource && <span className="camera-fps-badge">{fps} FPS</span>}
        </div>
        {(!hasSource || paused) && (
          <div className="camera-placeholder">
            <strong>◎</strong>
            <p>{paused ? "Xem trước đang tạm dừng" : "Đang chờ kết nối camera"}</p>
          </div>
        )}
      </div>
    </div>
    <div className={`camera-result${verified ? " confirmed" : ""}`} aria-live="polite"><p className="eyebrow">{verified ? "KẾT QUẢ XÁC NHẬN" : "TRẠNG THÁI CAMERA"}</p><h3>{title}</h3>{verified ? <p className="camera-student">{result?.student_code}</p> : <p>{error || reason}</p>}{preview?.received_at && hasSource && <small>Nhận lúc {new Date(preview.received_at).toLocaleTimeString("vi-VN")}</small>}{result?.pad_score !== undefined && <small>Độ tin cậy: {(result.pad_score * 100).toFixed(1)}%</small>}<hr /><small>{preview?.config.active ? `Gán buổi học #${preview.config.session_id}` : "Camera chưa gán vào buổi học nào."}</small></div>
  </section>;
}
