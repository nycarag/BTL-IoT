import { useEffect, useRef, useState } from "react";

export type DeviceConfig = {
  device_id?: string;
  session_id: number | null;
  active: boolean;
  roi_left: number;
  roi_top: number;
  roi_right: number;
  roi_bottom: number;
};

export type RecognitionResult = {
  accepted?: boolean;
  created?: boolean;
  reason?: string;
  state?: string;
  student_code?: string;
  student_name?: string;
  pad_score?: number;
  box?: number[];
  frame_size?: number[];
  distance?: number;
};

export type Preview = {
  type?: string;
  available: boolean;
  received_at?: string;
  session_id?: number | null;
  config: DeviceConfig;
  result?: RecognitionResult;
  is_preview?: boolean;
  sequence?: number;
  result_age_seconds?: number;
};

export type OverlayRect = {
  left: string;
  top: string;
  width: string;
  height: string;
};

export function computeContainOverlay(
  box: number[] | undefined,
  frameSize: number[] | undefined,
  canvasWidth: number,
  canvasHeight: number
): OverlayRect | null {
  if (!box || box.length < 4 || !frameSize || frameSize.length < 2) return null;
  const [x, y, w, h] = box;
  const [fw, fh] = frameSize;
  if (fw <= 0 || fh <= 0 || canvasWidth <= 0 || canvasHeight <= 0) return null;

  const frameAspect = fw / fh;
  const canvasAspect = canvasWidth / canvasHeight;

  let renderW = canvasWidth;
  let renderH = canvasHeight;
  let offsetX = 0;
  let offsetY = 0;

  if (canvasAspect > frameAspect) {
    renderW = canvasHeight * frameAspect;
    offsetX = (canvasWidth - renderW) / 2;
  } else {
    renderH = canvasWidth / frameAspect;
    offsetY = (canvasHeight - renderH) / 2;
  }

  return {
    left: `${offsetX + (x / fw) * renderW}px`,
    top: `${offsetY + (y / fh) * renderH}px`,
    width: `${(w / fw) * renderW}px`,
    height: `${(h / fh) * renderH}px`,
  };
}

export function computeRoiOverlay(
  roi: DeviceConfig | undefined,
  frameSize: number[] | undefined,
  canvasWidth: number,
  canvasHeight: number
): OverlayRect | null {
  if (!roi || canvasWidth <= 0 || canvasHeight <= 0) return null;
  const fw = frameSize?.[0] || 4;
  const fh = frameSize?.[1] || 3;
  const frameAspect = fw / fh;
  const canvasAspect = canvasWidth / canvasHeight;

  let renderW = canvasWidth;
  let renderH = canvasHeight;
  let offsetX = 0;
  let offsetY = 0;

  if (canvasAspect > frameAspect) {
    renderW = canvasHeight * frameAspect;
    offsetX = (canvasWidth - renderW) / 2;
  } else {
    renderH = canvasWidth / frameAspect;
    offsetY = (canvasHeight - renderH) / 2;
  }

  return {
    left: `${offsetX + roi.roi_left * renderW}px`,
    top: `${offsetY + roi.roi_top * renderH}px`,
    width: `${(roi.roi_right - roi.roi_left) * renderW}px`,
    height: `${(roi.roi_bottom - roi.roi_top) * renderH}px`,
  };
}

export function useCameraStream(
  deviceId: string,
  token: string,
  apiUrl: string,
  paused: boolean
) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [meta, setMeta] = useState<Preview | null>(null);
  const [fps, setFps] = useState<number>(0);
  const [connected, setConnected] = useState<boolean>(false);
  const [error, setError] = useState<string>("");
  const [canvasSize, setCanvasSize] = useState<{ width: number; height: number }>({ width: 0, height: 0 });

  const pendingBitmapRef = useRef<ImageBitmap | null>(null);
  const rafIdRef = useRef<number>(0);
  const frameTimestampsRef = useRef<number[]>([]);
  const lastFpsUpdateRef = useRef<number>(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width > 0 && height > 0) {
          setCanvasSize({ width, height });
        }
      }
    });
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [connected]);

  useEffect(() => {
    if (!deviceId || paused) {
      setConnected(false);
      setFps(0);
      if (pendingBitmapRef.current) {
        pendingBitmapRef.current.close();
        pendingBitmapRef.current = null;
      }
      return;
    }

    let stopped = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: number | null = null;

    const renderFrame = () => {
      rafIdRef.current = 0;
      const bitmap = pendingBitmapRef.current;
      if (!bitmap) return;
      pendingBitmapRef.current = null;

      const canvas = canvasRef.current;
      if (canvas) {
        if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
          canvas.width = bitmap.width;
          canvas.height = bitmap.height;
        }
        const ctx = canvas.getContext("2d");
        if (ctx) {
          ctx.drawImage(bitmap, 0, 0);
        }
      }
      bitmap.close();
    };

    const recordFps = () => {
      const now = performance.now();
      const timestamps = frameTimestampsRef.current;
      timestamps.push(now);
      while (timestamps.length > 0 && timestamps[0] < now - 1000) {
        timestamps.shift();
      }
      if (now - lastFpsUpdateRef.current >= 500) {
        lastFpsUpdateRef.current = now;
        setFps(timestamps.length);
      }
    };

    const connect = () => {
      if (stopped) return;
      const baseOrigin = apiUrl || window.location.origin;
      const url = new URL(`/ws/devices/${encodeURIComponent(deviceId)}/camera`, baseOrigin);
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";

      socket = new WebSocket(url);
      socket.binaryType = "blob";

      socket.onopen = () => {
        if (stopped) {
          socket?.close();
          return;
        }
        socket?.send(JSON.stringify({ token }));
        setConnected(true);
        setError("");
      };

      socket.onmessage = async (event) => {
        if (stopped) return;
        if (typeof event.data === "string") {
          try {
            const data = JSON.parse(event.data);
            if (data.type === "meta") {
              setMeta(data);
            }
          } catch {
            // ignore non-json messages
          }
          return;
        }

        const blob: Blob = event.data;
        const currentSocket = socket;
        try {
          const bitmap = await createImageBitmap(blob);
          if (stopped) {
            bitmap.close();
            return;
          }

          // Send ACK "next" immediately after createImageBitmap completes
          if (currentSocket && currentSocket.readyState === WebSocket.OPEN) {
            currentSocket.send("next");
          }

          // Store latest bitmap, closing unrendered older bitmap
          if (pendingBitmapRef.current) {
            pendingBitmapRef.current.close();
          }
          pendingBitmapRef.current = bitmap;
          setConnected(true);
          setError("");

          // Schedule rendering on animation frame (latest frame only)
          if (!rafIdRef.current) {
            rafIdRef.current = requestAnimationFrame(renderFrame);
          }

          recordFps();
        } catch {
          // If decode failed, still send next to keep pipeline flowing
          if (!stopped && currentSocket && currentSocket.readyState === WebSocket.OPEN) {
            currentSocket.send("next");
          }
        }
      };

      socket.onclose = (event) => {
        if (stopped) return;
        setConnected(false);
        setFps(0);
        if (event.code === 4401) {
          setError("Phiên xem camera hết hạn — đăng nhập lại");
        } else {
          setError("Đang kết nối lại luồng camera…");
          reconnectTimer = window.setTimeout(connect, 1000);
        }
      };

      socket.onerror = () => {
        socket?.close();
      };
    };

    connect();

    return () => {
      stopped = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (rafIdRef.current) {
        cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = 0;
      }
      if (pendingBitmapRef.current) {
        pendingBitmapRef.current.close();
        pendingBitmapRef.current = null;
      }
      if (socket) {
        socket.close();
        socket = null;
      }
      frameTimestampsRef.current = [];
      setFps(0);
    };
  }, [deviceId, token, apiUrl, paused]);

  return { canvasRef, meta, fps, connected, error, canvasSize };
}
