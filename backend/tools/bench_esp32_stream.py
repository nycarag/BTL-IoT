#!/usr/bin/env python3
"""
bench_esp32_stream.py - Công cụ đo kiểm hiệu năng luồng video ESP32-CAM MJPEG.
Chỉ sử dụng thư viện chuẩn Python.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

FRAMESIZE_ENUMS: dict[str, int] = {
    "QVGA": 6,
    "CIF": 8,
    "HVGA": 9,
    "VGA": 10,
}

ENUM_TO_FRAMESIZE: dict[int, str] = {v: k for k, v in FRAMESIZE_ENUMS.items()}

SWEEP_COMBINATIONS: list[tuple[str, int]] = [
    ("QVGA", 12),
    ("CIF", 12),
    ("CIF", 15),
    ("HVGA", 12),
    ("VGA", 12),
    ("VGA", 15),
]


def percentile(data: list[float], p: float) -> float:
    """Tính phân vị p (0-100) trên danh sách số thực."""
    if not data:
        return 0.0
    if len(data) == 1:
        return round(data[0], 2)
    sorted_d = sorted(data)
    k = (len(sorted_d) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_d) - 1)
    d = k - f
    val = sorted_d[f] + d * (sorted_d[c] - sorted_d[f])
    return round(val, 2)


def jpeg_frames(response, max_frame_bytes: int = 5 * 1024 * 1024):
    """
    Tách các frame JPEG từ luồng multipart MJPEG dựa trên SOI (\\xff\\xd8) và EOI (\\xff\\xd9),
    tương thích với cơ chế tách khung của camera_bridge.py.
    """
    buffer = bytearray()
    read = getattr(response, "read1", response.read)
    while True:
        chunk = read(16384)
        if not chunk:
            break
        buffer.extend(chunk)
        while True:
            start = buffer.find(b"\xff\xd8")
            if start < 0:
                if len(buffer) > 65536:
                    del buffer[:-1]
                break
            if start > 0:
                del buffer[:start]
            end = buffer.find(b"\xff\xd9", 2)
            if end < 0:
                if len(buffer) > max_frame_bytes:
                    buffer.clear()
                break
            if end + 2 > max_frame_bytes:
                buffer.clear()
                break
            yield bytes(buffer[: end + 2])
            del buffer[: end + 2]


def parse_camera_urls(base_url: str, custom_stream_url: str | None = None) -> tuple[str, str]:
    """Phân tách URL gốc thành base URL quản trị (port 80) và stream URL (port 81)."""
    parsed = urlsplit(base_url if "://" in base_url else f"http://{base_url}")
    scheme = parsed.scheme or "http"
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port

    if custom_stream_url:
        stream_url = custom_stream_url
    elif port is None or port == 80:
        stream_url = f"{scheme}://{host}:81/stream"
    else:
        stream_url = f"{scheme}://{host}:{port}/stream"

    if port is None:
        status_base = f"{scheme}://{host}"
    else:
        status_base = f"{scheme}://{host}:{port}"

    return status_base, stream_url


def get_camera_status(base_url: str, timeout: float = 2.0) -> dict | None:
    """Gọi GET /status để lấy trạng thái camera."""
    url = f"{base_url.rstrip('/')}/status"
    try:
        req = Request(url)
        with urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                fs_val = data.get("framesize")
                fs_name = ENUM_TO_FRAMESIZE.get(fs_val, str(fs_val))
                return {
                    "wifi_mode": data.get("wifi_mode"),
                    "rssi": data.get("rssi"),
                    "stream_fps": data.get("stream_fps"),
                    "framesize": fs_val,
                    "framesize_name": fs_name,
                    "quality": data.get("quality"),
                    "free_heap": data.get("free_heap"),
                    "uptime_s": data.get("uptime_s"),
                    "psram": data.get("psram"),
                }
    except Exception:
        pass
    return None


def set_camera_control(base_url: str, var: str, val: int, timeout: float = 2.0) -> tuple[bool, int, dict | None]:
    """Gọi GET /control?var=...&val=... để thay đổi thông số cảm biến."""
    url = f"{base_url.rstrip('/')}/control?var={var}&val={val}"
    try:
        req = Request(url)
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return True, resp.status, data
    except HTTPError as e:
        try:
            err_data = json.loads(e.read().decode("utf-8"))
        except Exception:
            err_data = None
        return False, e.code, err_data
    except Exception:
        return False, 0, None


def measure_latency(base_url: str, count: int = 20) -> dict:
    """Đo độ trễ mạng: 20 lần GET /status, ghi p50 và p95 (ms)."""
    latencies: list[float] = []
    url = f"{base_url.rstrip('/')}/status"
    for _ in range(count):
        try:
            t0 = time.perf_counter()
            req = Request(url)
            with urlopen(req, timeout=2.0) as resp:
                resp.read()
            t1 = time.perf_counter()
            latencies.append((t1 - t0) * 1000.0)
        except Exception:
            pass
        time.sleep(0.01)

    if not latencies:
        return {"p50_ms": None, "p95_ms": None, "samples": 0}

    return {
        "p50_ms": percentile(latencies, 50),
        "p95_ms": percentile(latencies, 95),
        "samples": len(latencies),
    }


def measure_stream(stream_url: str, duration: float, max_frames: int | None = None) -> dict:
    """
    Đo luồng MJPEG trong khoảng thời gian duration (giây).
    Đo: số frame, fps trung bình, khoảng cách giữa 2 frame (p50/p95/p99/max ms),
    số lần khựng (> 250 ms), kbps, kích thước frame trung bình.
    """
    intervals_ms: list[float] = []
    frame_count = 0
    total_bytes = 0
    last_frame_time: float | None = None
    first_frame_time: float | None = None

    req = Request(stream_url)
    t_start = time.perf_counter()

    try:
        with urlopen(req, timeout=5.0) as resp:
            for frame in jpeg_frames(resp):
                now = time.perf_counter()
                frame_time = now
                if first_frame_time is None:
                    first_frame_time = frame_time
                if last_frame_time is not None:
                    intervals_ms.append((frame_time - last_frame_time) * 1000.0)
                last_frame_time = frame_time
                frame_count += 1
                total_bytes += len(frame)

                if max_frames is not None and frame_count >= max_frames:
                    break
                if duration > 0 and (now - t_start) >= duration:
                    break
    except (OSError, HTTPError, TimeoutError):
        pass

    t_end = time.perf_counter()
    if last_frame_time and first_frame_time and last_frame_time > first_frame_time:
        actual_duration = last_frame_time - first_frame_time
    else:
        actual_duration = t_end - t_start if (t_end - t_start) > 0 else 0.001

    avg_fps = round(frame_count / actual_duration, 2) if actual_duration > 0 else 0.0
    kbps = round((total_bytes * 8.0) / (actual_duration * 1000.0), 2) if actual_duration > 0 else 0.0
    avg_frame_size = round(total_bytes / frame_count, 2) if frame_count > 0 else 0.0
    stutters = sum(1 for dt in intervals_ms if dt > 250.0)

    p50 = percentile(intervals_ms, 50)
    p95 = percentile(intervals_ms, 95)
    p99 = percentile(intervals_ms, 99)
    max_interval = round(max(intervals_ms), 2) if intervals_ms else 0.0

    return {
        "frame_count": frame_count,
        "duration_s": round(actual_duration, 2),
        "avg_fps": avg_fps,
        "kbps": kbps,
        "avg_frame_size_bytes": avg_frame_size,
        "interval_p50_ms": p50,
        "interval_p95_ms": p95,
        "interval_p99_ms": p99,
        "interval_max_ms": max_interval,
        "stutter_count": stutters,
    }


def run_benchmark(
    base_url: str,
    seconds: float,
    label: str,
    sweep: bool = False,
    sweep_delay: float = 2.0,
    custom_stream_url: str | None = None,
) -> dict:
    """Thực thi toàn bộ kịch bản đo kiểm."""
    status_base, stream_url = parse_camera_urls(base_url, custom_stream_url)

    # 1. Đo latency mạng và lấy status trước khi đo
    latency = measure_latency(status_base, count=20)
    status_before = get_camera_status(status_base)

    # 2. Đo luồng ở cấu hình hiện tại
    stream_metrics = measure_stream(stream_url, duration=seconds)

    # 3. Lấy status sau khi đo
    status_after = get_camera_status(status_base)

    result: dict = {
        "label": label,
        "url": base_url,
        "status_url": f"{status_base}/status",
        "stream_url": stream_url,
        "seconds": seconds,
        "status_before": status_before,
        "status_after": status_after,
        "latency": latency,
        "stream": stream_metrics,
    }

    # 4. Kịch bản sweep (nếu có yêu cầu)
    if sweep:
        sweep_results: list[dict] = []
        if status_before is None:
            # Firmware cũ không có /status hoặc /control
            print("CẢNH BÁO: Firmware không phản hồi /status hoặc /control. Bỏ qua chế độ --sweep, chỉ đo cấu hình hiện tại.", file=sys.stderr)
            result["sweep"] = None
            return result

        orig_framesize = status_before.get("framesize")
        orig_quality = status_before.get("quality")

        for fs_name, q_val in SWEEP_COMBINATIONS:
            fs_code = FRAMESIZE_ENUMS[fs_name]
            cfg_label = f"({fs_name}, q{q_val})"

            # Đặt framesize
            ok_fs, code_fs, _ = set_camera_control(status_base, "framesize", fs_code)
            if not ok_fs and code_fs == 400:
                sweep_results.append({
                    "config": cfg_label,
                    "framesize": fs_name,
                    "quality": q_val,
                    "supported": False,
                    "status": "không hỗ trợ",
                    "reason": "Camera trả mã 400",
                })
                continue
            elif not ok_fs:
                sweep_results.append({
                    "config": cfg_label,
                    "framesize": fs_name,
                    "quality": q_val,
                    "supported": False,
                    "status": "không hỗ trợ",
                    "reason": f"Lỗi HTTP {code_fs}",
                })
                continue

            # Đặt quality
            ok_q, code_q, _ = set_camera_control(status_base, "quality", q_val)
            if not ok_q:
                sweep_results.append({
                    "config": cfg_label,
                    "framesize": fs_name,
                    "quality": q_val,
                    "supported": False,
                    "status": "không hỗ trợ",
                    "reason": f"Lỗi quality HTTP {code_q}",
                })
                continue

            # Chờ ổn định
            time.sleep(sweep_delay)

            # Đo luồng
            m = measure_stream(stream_url, duration=seconds)
            sweep_results.append({
                "config": cfg_label,
                "framesize": fs_name,
                "quality": q_val,
                "supported": True,
                "status": "OK",
                "stream": m,
            })

        # Trả lại cấu hình ban đầu
        if orig_framesize is not None:
            set_camera_control(status_base, "framesize", int(orig_framesize))
        if orig_quality is not None:
            set_camera_control(status_base, "quality", int(orig_quality))

        result["sweep"] = sweep_results

    return result


def print_summary_table(result: dict) -> None:
    """In bảng tóm tắt kết quả đo gọn gàng ra stdout."""
    label = result.get("label", "")
    url = result.get("url", "")
    print("\n" + "=" * 80)
    print(f"ESP32-CAM STREAM BENCHMARK: [{label}] (Base URL: {url})")
    print("=" * 80)

    sb = result.get("status_before")
    sa = result.get("status_after")
    if sb:
        print(f"Status Trước : mode={sb.get('wifi_mode')}, rssi={sb.get('rssi')}, framesize={sb.get('framesize_name')}, quality={sb.get('quality')}, stream_fps={sb.get('stream_fps')}")
    else:
        print("Status Trước : null (Không phản hồi /status)")
    if sa:
        print(f"Status Sau   : mode={sa.get('wifi_mode')}, rssi={sa.get('rssi')}, framesize={sa.get('framesize_name')}, quality={sa.get('quality')}, stream_fps={sa.get('stream_fps')}")
    else:
        print("Status Sau   : null (Không phản hồi /status)")

    lat = result.get("latency", {})
    if lat.get("p50_ms") is not None:
        print(f"Độ trễ mạng  : p50={lat['p50_ms']} ms | p95={lat['p95_ms']} ms ({lat.get('samples', 0)} lần GET /status)")
    else:
        print("Độ trễ mạng  : null (Không đo được /status)")

    sm = result.get("stream")
    if sm:
        print("-" * 80)
        print(f"Đo luồng ({sm.get('duration_s', 0)}s):")
        print(f"  Số frame nhận   : {sm.get('frame_count')} frames")
        print(f"  FPS trung bình  : {sm.get('avg_fps')} fps")
        print(f"  Băng thông      : {sm.get('kbps')} kbps (kích thước TB: {sm.get('avg_frame_size_bytes')} bytes/frame)")
        print(f"  Khoảng cách (ms): p50={sm.get('interval_p50_ms')} ms | p95={sm.get('interval_p95_ms')} ms | p99={sm.get('interval_p99_ms')} ms | max={sm.get('interval_max_ms')} ms")
        print(f"  Số lần khựng    : {sm.get('stutter_count')} lần (> 250 ms)")
        print("-" * 80)

    sweep = result.get("sweep")
    if sweep:
        print("\nKết quả Sweep các tổ hợp độ phân giải / nén:")
        print(f"  {'Tổ hợp':<14} {'Trạng thái':<16} {'Frames':<8} {'FPS':<8} {'p50 (ms)':<10} {'p95 (ms)':<10} {'Khựng':<8} {'Băng thông'}")
        print("  " + "-" * 78)
        for s in sweep:
            cfg = s.get("config", "")
            st = s.get("status", "")
            if s.get("supported"):
                m = s.get("stream", {})
                print(f"  {cfg:<14} {st:<16} {m.get('frame_count', 0):<8} {m.get('avg_fps', 0):<8} {m.get('interval_p50_ms', 0):<10} {m.get('interval_p95_ms', 0):<10} {m.get('stutter_count', 0):<8} {m.get('kbps', 0)} kbps")
            else:
                reason = s.get("reason", "không hỗ trợ")
                print(f"  {cfg:<14} {reason:<16} {'-':<8} {'-':<8} {'-':<10} {'-':<10} {'-':<8} -")
    print("=" * 80 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Đo kiểm hiệu năng và độ mượt luồng video ESP32-CAM MJPEG.")
    parser.add_argument("--url", required=True, help="URL gốc của ESP32-CAM (vd: http://192.168.4.1 hoặc http://192.168.1.50)")
    parser.add_argument("--seconds", type=float, default=30.0, help="Thời gian đo luồng video mỗi cấu hình (giây, mặc định 30)")
    parser.add_argument("--label", default="A-ap", help="Nhãn kịch bản đo (vd: 'A-ap', 'B-sta-hotspot')")
    parser.add_argument("--sweep", action="store_true", help="Quét qua 6 tổ hợp framesize và quality")
    parser.add_argument("--sweep-delay", type=float, default=2.0, help="Thời gian chờ ổn định giữa các tổ hợp sweep (giây, mặc định 2.0)")
    parser.add_argument("--stream-url", default=None, help="URL luồng stream trực tiếp nếu khác cổng 81")
    parser.add_argument("--out", default=None, help="Đường dẫn file JSON xuất kết quả đo")

    args = parser.parse_args()

    result = run_benchmark(
        base_url=args.url,
        seconds=args.seconds,
        label=args.label,
        sweep=args.sweep,
        sweep_delay=args.sweep_delay,
        custom_stream_url=args.stream_url,
    )

    print_summary_table(result)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"Đã lưu kết quả JSON vào: {args.out}")


if __name__ == "__main__":
    main()
