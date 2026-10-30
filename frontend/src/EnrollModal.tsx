import { useState, useRef, useEffect, ChangeEvent, FormEvent } from "react";

type Student = {
  id: number;
  student_code: string;
  name: string;
  class_id: number | null;
  date_of_birth: string | null;
  enrolled: boolean;
};

type Props = {
  student: Student;
  className: string;
  api: (path: string, init?: RequestInit) => Promise<Response>;
  onClose: () => void;
  onSuccess: () => Promise<void>;
};

export default function EnrollModal({ student, className, api, onClose, onSuccess }: Props) {
  const [mode, setMode] = useState<"webcam" | "upload">("webcam");
  const [capturedBlobs, setCapturedBlobs] = useState<{ id: string; blob: Blob; url: string }[]>([]);
  const [selectedFiles, setSelectedFiles] = useState<{ id: string; file: File; url: string }[]>([]);
  const [consent, setConsent] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [successMsg, setSuccessMsg] = useState("");

  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);

  // Khởi động Webcam khi chuyển sang mode "webcam"
  useEffect(() => {
    let active = true;
    if (mode === "webcam") {
      navigator.mediaDevices
        ?.getUserMedia({ video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" } })
        .then(stream => {
          if (!active) {
            stream.getTracks().forEach(t => t.stop());
            return;
          }
          streamRef.current = stream;
          if (videoRef.current) {
            videoRef.current.srcObject = stream;
          }
        })
        .catch(err => {
          if (active) {
            setError(`Không thể mở Webcam: ${err.message}. Bạn có thể chuyển sang tab 'Tải ảnh lên'.`);
          }
        });
    }

    return () => {
      active = false;
      if (streamRef.current) {
        streamRef.current.getTracks().forEach(t => t.stop());
        streamRef.current = null;
      }
    };
  }, [mode]);

  // Giải phóng object URLs khi đóng component
  useEffect(() => {
    return () => {
      capturedBlobs.forEach(b => URL.revokeObjectURL(b.url));
      selectedFiles.forEach(f => URL.revokeObjectURL(f.url));
    };
  }, [capturedBlobs, selectedFiles]);

  const handleCapture = () => {
    if (!videoRef.current) return;
    const video = videoRef.current;
    if (video.videoWidth === 0 || video.videoHeight === 0) return;

    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(
      blob => {
        if (!blob) return;
        if (capturedBlobs.length >= 3) {
          setError("Tối đa 3 ảnh mẫu. Vui lòng xóa bớt ảnh nếu muốn chụp lại.");
          return;
        }
        const url = URL.createObjectURL(blob);
        setCapturedBlobs(prev => [...prev, { id: Math.random().toString(), blob, url }]);
        setError("");
      },
      "image/jpeg",
      0.92
    );
  };

  const removeCaptured = (id: string) => {
    setCapturedBlobs(prev => {
      const target = prev.find(p => p.id === id);
      if (target) URL.revokeObjectURL(target.url);
      return prev.filter(p => p.id !== id);
    });
  };

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files) return;
    const files = Array.from(e.target.files);
    if (files.length + selectedFiles.length > 5) {
      setError("Chỉ được chọn tối đa 5 ảnh chân dung.");
      return;
    }
    const newItems = files.map(file => ({
      id: Math.random().toString(),
      file,
      url: URL.createObjectURL(file)
    }));
    setSelectedFiles(prev => [...prev, ...newItems]);
    setError("");
  };

  const removeFile = (id: string) => {
    setSelectedFiles(prev => {
      const target = prev.find(p => p.id === id);
      if (target) URL.revokeObjectURL(target.url);
      return prev.filter(p => p.id !== id);
    });
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!consent) {
      setError("Cần xác nhận cam kết đồng ý sử dụng dữ liệu sinh trắc học.");
      return;
    }

    const formData = new FormData();
    formData.append("consent", "true");

    if (mode === "webcam") {
      if (capturedBlobs.length === 0) {
        setError("Vui lòng chụp ít nhất 1 bức ảnh chân dung rõ mặt từ webcam.");
        return;
      }
      capturedBlobs.forEach((item, idx) => {
        formData.append("image", item.blob, `webcam_snap_${idx + 1}.jpg`);
      });
    } else {
      if (selectedFiles.length === 0) {
        setError("Vui lòng chọn ít nhất 1 tệp ảnh chân dung từ máy tính.");
        return;
      }
      selectedFiles.forEach(item => {
        formData.append("image", item.file, item.file.name);
      });
    }

    setBusy(true);
    setError("");
    setSuccessMsg("");

    try {
      const response = await api(`/students/${student.id}/face`, {
        method: "POST",
        body: formData
      });
      const data = await response.json();
      setSuccessMsg(`✓ Đã đăng ký thành công ${data.samples || 1} mẫu khuôn mặt cho ${student.name}!`);
      await onSuccess();
      setTimeout(() => {
        onClose();
      }, 1200);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Đăng ký khuôn mặt thất bại.");
    } finally {
      setBusy(false);
    }
  };

  const handleRevoke = async () => {
    if (!confirm(`Thu hồi toàn bộ dữ liệu khuôn mặt của sinh viên ${student.name} (${student.student_code})?`)) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api(`/students/${student.id}/face`, { method: "DELETE" });
      setSuccessMsg("✓ Đã thu hồi dữ liệu khuôn mặt.");
      await onSuccess();
      setTimeout(() => {
        onClose();
      }, 1000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không thể thu hồi dữ liệu.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={e => { if (e.target === e.currentTarget && !busy) onClose(); }}>
      <div className="modal-card enroll-modal">
        <div className="modal-header">
          <div>
            <span className="modal-eyebrow">ĐĂNG KÝ SINH TRẮC HỌC KHUÔN MẶT</span>
            <h2>{student.name} · <small>{student.student_code}</small></h2>
            <p className="modal-sub">Lớp: <strong>{className}</strong> · {student.enrolled ? <span className="badge open">✓ Đã có embedding</span> : <span className="badge offline">Chưa đăng ký</span>}</p>
          </div>
          <button type="button" className="modal-close-btn" disabled={busy} onClick={onClose}>✕</button>
        </div>

        {error && <div className="message error" role="alert">{error}</div>}
        {successMsg && <div className="message" role="status" style={{ background: "#e8f5e9", color: "#2e7d32", fontWeight: 600 }}>{successMsg}</div>}

        <div className="enroll-tabs">
          <button
            type="button"
            className={`tab-btn ${mode === "webcam" ? "active" : ""}`}
            onClick={() => { setMode("webcam"); setError(""); }}
            disabled={busy}
          >
            📸 Chụp từ Webcam Laptop
          </button>
          <button
            type="button"
            className={`tab-btn ${mode === "upload" ? "active" : ""}`}
            onClick={() => { setMode("upload"); setError(""); }}
            disabled={busy}
          >
            📁 Tải ảnh từ máy tính
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          {mode === "webcam" ? (
            <div className="webcam-section">
              <div className="webcam-viewport">
                <video ref={videoRef} autoPlay playsInline muted className="webcam-video" />
                <div className="webcam-face-guide">
                  <div className="oval-outline"></div>
                  <span>CĂN MẶT TRONG KHUNG</span>
                </div>
              </div>
              <div className="webcam-controls">
                <button
                  type="button"
                  className="snap-btn"
                  onClick={handleCapture}
                  disabled={busy || capturedBlobs.length >= 3}
                >
                  📷 Bấm chụp ảnh ({capturedBlobs.length}/3)
                </button>
                <small className="muted">Khuyên chụp 1–3 ảnh: 1 chính diện, 1 hơi nghiêng trái nhẹ, 1 hơi nghiêng phải nhẹ.</small>
              </div>

              {capturedBlobs.length > 0 && (
                <div className="preview-row">
                  {capturedBlobs.map((item, idx) => (
                    <div key={item.id} className="preview-thumb">
                      <img src={item.url} alt={`Mẫu ${idx + 1}`} />
                      <span className="thumb-tag">Mẫu #{idx + 1}</span>
                      <button type="button" className="thumb-remove" onClick={() => removeCaptured(item.id)} disabled={busy}>✕</button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="upload-section">
              <div className="dropzone-box">
                <input
                  type="file"
                  id="enroll-file-input"
                  accept="image/jpeg,image/png"
                  multiple
                  onChange={handleFileChange}
                  disabled={busy}
                  style={{ display: "none" }}
                />
                <label htmlFor="enroll-file-input" className="dropzone-label">
                  <span className="dropzone-icon">📥</span>
                  <strong>Chọn tệp ảnh từ máy tính</strong>
                  <p>Hỗ trợ định dạng JPEG, PNG (dung lượng tối đa 5MB/ảnh).</p>
                  <span className="dropzone-btn">Chọn ảnh...</span>
                </label>
              </div>

              {selectedFiles.length > 0 && (
                <div className="preview-row">
                  {selectedFiles.map(item => (
                    <div key={item.id} className="preview-thumb">
                      <img src={item.url} alt={item.file.name} />
                      <span className="thumb-tag">{item.file.name}</span>
                      <button type="button" className="thumb-remove" onClick={() => removeFile(item.id)} disabled={busy}>✕</button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          <div className="consent-box">
            <label className="check">
              <input
                type="checkbox"
                checked={consent}
                onChange={e => setConsent(e.target.checked)}
                required
                disabled={busy}
              />
              <span>Đã có sự đồng ý của sinh viên cho mục đích điểm danh lớp học; giảng viên đã đối chiếu danh tính thực tế.</span>
            </label>
            <small className="muted">Hệ thống chỉ trích xuất vector embedding 128D; không lưu trữ ảnh thô trên máy chủ để bảo vệ quyền riêng tư.</small>
          </div>

          <div className="modal-actions">
            {student.enrolled && (
              <button
                type="button"
                className="danger"
                disabled={busy}
                onClick={handleRevoke}
              >
                Thu hồi dữ liệu mặt
              </button>
            )}
            <div style={{ marginLeft: "auto", display: "flex", gap: "10px" }}>
              <button type="button" className="secondary" disabled={busy} onClick={onClose}>
                Hủy
              </button>
              <button
                type="submit"
                disabled={busy || (mode === "webcam" ? capturedBlobs.length === 0 : selectedFiles.length === 0)}
              >
                {busy ? "Đang mã hóa dlib 128D..." : "Lưu embedding khuôn mặt"}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
