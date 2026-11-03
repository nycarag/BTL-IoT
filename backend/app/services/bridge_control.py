"""Bridge lifecycle controller: spawn, monitor and terminate camera_bridge.py safely.

Reference: dtkien205 (same group, shared origin) in scratchpad/ref/backend/app/services/bridge_control.py.
"""
from __future__ import annotations

import collections
import ipaddress
import logging
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit

from app.core.config import settings
from app.services.camera_preview import previews

logger = logging.getLogger("bridge-control")


def is_private_or_loopback_ip(ip_str: str) -> bool:
    """Check if an IP address string belongs to private or loopback ranges."""
    try:
        ip = ipaddress.ip_address(ip_str.strip())
        return ip.is_private or ip.is_loopback
    except ValueError:
        return False


def validate_camera_url(url: str) -> str:
    """Validate camera URL to prevent SSRF: only HTTP(S) to private LAN or loopback addresses."""
    if not url or not isinstance(url, str):
        raise ValueError("Camera URL must be a non-empty string")

    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Invalid URL scheme '{parsed.scheme}': only http and https are allowed")
    if not parsed.hostname:
        raise ValueError("Camera URL must include a valid hostname or IP address")
    if parsed.username or parsed.password:
        raise ValueError("Camera URL must not contain embedded user credentials")

    hostname = parsed.hostname.strip()
    if hostname.lower() == "localhost":
        return url

    # Try parsing directly as an IP address literal
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if not is_private_or_loopback_ip(hostname):
            raise ValueError(f"Camera IP '{hostname}' is not a private LAN or loopback address (SSRF protection)")
        return url

    # For domain hostnames: resolve and ensure all resolved IP addresses are private/loopback
    try:
        addr_info = socket.getaddrinfo(hostname, None)
        if not addr_info:
            raise ValueError(f"Cannot resolve hostname '{hostname}'")
        for entry in addr_info:
            sockaddr = entry[4]
            ip_candidate = sockaddr[0]
            if not is_private_or_loopback_ip(ip_candidate):
                raise ValueError(
                    f"Resolved IP '{ip_candidate}' for hostname '{hostname}' is not private/loopback (SSRF protection)"
                )
    except socket.gaierror as exc:
        raise ValueError(f"Failed to resolve camera hostname '{hostname}': {exc}")

    return url


class BridgeControl:
    """Thread-safe controller for managing one background camera_bridge process."""

    def __init__(self) -> None:
        self.process: subprocess.Popen | None = None
        self.lock = threading.RLock()
        self._source: str | None = None
        self._camera_url: str | None = None
        self._stderr_lines: collections.deque[str] = collections.deque(maxlen=20)
        self._reader_thread: threading.Thread | None = None

    @property
    def device_id(self) -> str:
        if self._source == "webcam":
            return "webcam-01"
        return os.getenv("CAMERA_DEVICE_ID", "esp32-cam-01")

    def _resolve_script(self) -> Path:
        script = Path(__file__).resolve().parents[2] / "camera_bridge.py"
        if not script.is_file():
            raise FileNotFoundError(f"Cannot locate camera_bridge.py script at {script}")
        return script

    def status(self) -> dict:
        with self.lock:
            running = False
            pid = None
            if self.process is not None:
                if self.process.poll() is None:
                    running = True
                    pid = self.process.pid
                else:
                    self.process = None

            current_device_id = self.device_id
            connected = previews.get(current_device_id) is not None
            return {
                "running": running,
                "pid": pid,
                "source": self._source if running else None,
                "device_id": current_device_id,
                "camera_url": self._camera_url if running else None,
                "connected": connected,
                "recent_errors": list(self._stderr_lines),
            }

    def start(self, source: str = "webcam", camera_url: str | None = None) -> dict:
        if source not in {"webcam", "esp32"}:
            raise ValueError(f"Invalid camera source '{source}': must be 'webcam' or 'esp32'")

        with self.lock:
            if self.process is not None and self.process.poll() is None:
                raise RuntimeError("Camera bridge is already running; stop the active process first")

            self._stderr_lines.clear()
            self._source = source

            if source == "webcam":
                self._camera_url = None
            else:
                target_url = camera_url or settings.default_camera_url
                validated_url = validate_camera_url(target_url)
                self._camera_url = validated_url

                parsed = urlsplit(validated_url)
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
                try:
                    with socket.create_connection((parsed.hostname, port), timeout=3):
                        pass
                except OSError as exc:
                    raise OSError(f"Cannot connect to ESP32-CAM at {parsed.hostname}:{port} ({exc})")

            script = self._resolve_script()
            cmd = [sys.executable, str(script)]
            if source == "webcam":
                cmd.append("--webcam")

            # Pass token strictly via environment variable to avoid exposure in ps/process lists
            env = dict(os.environ)
            env["DEVICE_TOKEN"] = settings.device_token
            env["BRIDGE_BACKEND_URL"] = f"http://127.0.0.1:{settings.backend_port}"
            env["CAMERA_DEVICE_ID"] = self.device_id
            if source == "esp32" and self._camera_url:
                env["CAMERA_CAPTURE_URL"] = self._camera_url

            self.process = subprocess.Popen(
                cmd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )

            def _read_stderr(pipe, lines: collections.deque[str]) -> None:
                try:
                    for line in iter(pipe.readline, b""):
                        text = line.decode("utf-8", errors="replace").rstrip()
                        if text:
                            lines.append(text)
                except Exception:
                    pass
                finally:
                    try:
                        pipe.close()
                    except Exception:
                        pass

            if self.process.stderr is not None:
                self._reader_thread = threading.Thread(
                    target=_read_stderr,
                    args=(self.process.stderr, self._stderr_lines),
                    daemon=True,
                    name="bridge-stderr-tail",
                )
                self._reader_thread.start()

            return self.status()

    def stop(self) -> dict:
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    try:
                        self.process.wait(timeout=2)
                    except Exception:
                        pass
            self.process = None
            return self.status()


bridge = BridgeControl()
