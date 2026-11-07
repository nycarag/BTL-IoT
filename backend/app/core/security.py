"""Authentication, password hashing, token issuance, revocation, and rate limiting."""

from __future__ import annotations

import base64
import hashlib
import hmac
import math
import os
import secrets
import threading
import time
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

bearer = HTTPBearer(auto_error=False)

# Danh sách thu hồi mất khi restart, chấp nhận vì token cũng sẽ hết hạn sau token_ttl_hours.
_revoked: dict[str, int] = {}
_revoked_lock = threading.Lock()


def hash_password(password: str, iterations: int = 600_000) -> str:
    """Hash mật khẩu sử dụng PBKDF2-HMAC-SHA256 với salt ngẫu nhiên 16 bytes."""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    salt_b64 = base64.urlsafe_b64encode(salt).decode("ascii")
    dk_b64 = base64.urlsafe_b64encode(dk).decode("ascii")
    return f"pbkdf2_sha256${iterations}${salt_b64}${dk_b64}"


def verify_password(password: str, encoded: str) -> bool:
    """Xác thực mật khẩu với chuỗi hash đã mã hóa. Trả về False nếu sai định dạng."""
    if not isinstance(encoded, str) or not encoded.startswith("pbkdf2_sha256$"):
        return False
    parts = encoded.split("$")
    if len(parts) != 4:
        return False
    _, iter_str, salt_b64, hash_b64 = parts
    try:
        iterations = int(iter_str)
        if iterations <= 0:
            return False
        salt = base64.urlsafe_b64decode(salt_b64 + "===")
        expected_dk = base64.urlsafe_b64decode(hash_b64 + "===")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(dk, expected_dk)
    except Exception:
        return False


def check_admin_password(password: str) -> bool:
    """Kiểm tra mật khẩu quản trị viên với admin_password_hash hoặc admin_password."""
    admin_password_hash = getattr(settings, "admin_password_hash", "") or os.getenv("ADMIN_PASSWORD_HASH", "")
    if admin_password_hash:
        return verify_password(password, admin_password_hash)
    if not settings.admin_password:
        return False
    return hmac.compare_digest(password.encode("utf-8"), settings.admin_password.encode("utf-8"))


class LoginThrottle:
    """In-memory rate limiter chống brute force mật khẩu theo (ip, username)."""

    def __init__(self, max_entries: int = 10_000) -> None:
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._failures: dict[tuple[str, str], list[float]] = {}
        self._locked_until: dict[tuple[str, str], float] = {}

    def _evict_if_needed(self) -> None:
        now = time.monotonic()
        total = len(self._failures) + len(self._locked_until)
        if total > self._max_entries:
            expired = [k for k, exp in self._locked_until.items() if exp <= now]
            for k in expired:
                del self._locked_until[k]
            while len(self._failures) + len(self._locked_until) > self._max_entries and self._failures:
                oldest_k = next(iter(self._failures))
                del self._failures[oldest_k]

    def check(self, key: tuple[str, str]) -> int | None:
        """Trả về số giây còn lại nếu đang bị khóa, ngược lại trả về None."""
        now = time.monotonic()
        with self._lock:
            locked_at = self._locked_until.get(key)
            if locked_at is not None:
                if locked_at > now:
                    return max(1, int(math.ceil(locked_at - now)))
                del self._locked_until[key]
                self._failures.pop(key, None)
            return None

    def fail(self, key: tuple[str, str]) -> bool:
        """Ghi nhận đăng nhập sai. Trả về True nếu số lần sai kích hoạt khóa tài khoản."""
        now = time.monotonic()
        window = getattr(settings, "login_window_seconds", 300)
        max_attempts = getattr(settings, "login_max_attempts", 5)
        lock_seconds = getattr(settings, "login_lock_seconds", 900)

        with self._lock:
            locked_at = self._locked_until.get(key)
            if locked_at is not None and locked_at > now:
                return True

            attempts = [t for t in self._failures.get(key, []) if t >= now - window]
            attempts.append(now)

            if len(attempts) >= max_attempts:
                self._locked_until[key] = now + lock_seconds
                self._failures.pop(key, None)
                self._evict_if_needed()
                return True

            self._failures[key] = attempts
            self._evict_if_needed()
            return False

    def success(self, key: tuple[str, str]) -> None:
        """Xóa lịch sử đăng nhập sai khi đăng nhập thành công."""
        with self._lock:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)

    def reset(self) -> None:
        """Xóa sạch toàn bộ bộ nhớ throttle (dùng cho testing)."""
        with self._lock:
            self._failures.clear()
            self._locked_until.clear()


login_throttle = LoginThrottle()


def _signature(payload: str) -> str:
    return hmac.new(
        settings.secret_key.encode("utf-8"), payload.encode("ascii"), hashlib.sha256
    ).hexdigest()


def issue_token(username: str) -> str:
    """Tạo token mới dạng username:expiry:jti kèm chữ ký HMAC-SHA256."""
    ttl_hours = getattr(settings, "token_ttl_hours", 8)
    expiry = int(time.time()) + int(ttl_hours) * 3600
    jti = secrets.token_urlsafe(12)
    payload = f"{username}:{expiry}:{jti}"
    encoded = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{encoded}.{_signature(encoded)}"


def revoke_token(token: str) -> None:
    """Thu hồi token bằng cách lưu jti vào danh sách _revoked."""
    try:
        raw = token.credentials if hasattr(token, "credentials") else token
        encoded, _ = str(raw).split(".", 1)
        payload = base64.urlsafe_b64decode(encoded + "===").decode("utf-8")
        parts = payload.rsplit(":", 2)
        if len(parts) == 3:
            _, expiry_str, jti = parts
            expiry = int(expiry_str)
            now = int(time.time())
            with _revoked_lock:
                expired = [k for k, exp in _revoked.items() if exp < now]
                for k in expired:
                    del _revoked[k]
                if expiry >= now:
                    _revoked[jti] = expiry
    except Exception:
        pass


def verify_token(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    """Xác thực token Bearer. Chặn token hết hạn, sai chữ ký, token cũ (2 phần) hoặc đã bị thu hồi."""
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")
    if not settings.secret_key:
        raise HTTPException(status_code=503, detail="Secret key is not configured")
    try:
        encoded, supplied_signature = credentials.credentials.split(".", 1)
        expected = _signature(encoded)
        if not hmac.compare_digest(expected, supplied_signature):
            raise ValueError
        payload = base64.urlsafe_b64decode(encoded + "===").decode("utf-8")
        parts = payload.rsplit(":", 2)
        if len(parts) != 3:
            raise ValueError
        username, expiry_str, jti = parts
        expiry = int(expiry_str)
        if username != settings.admin_username or expiry < int(time.time()):
            raise ValueError
        with _revoked_lock:
            if jti in _revoked:
                raise ValueError
        return username
    except (ValueError, TypeError, UnicodeError, base64.binascii.Error):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


def verify_device_token(token: str | None) -> None:
    if not token or not settings.device_token or not hmac.compare_digest(token.encode(), settings.device_token.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid device token")


if __name__ == "__main__":
    import getpass
    import sys

    p1 = getpass.getpass("Enter new admin password: ")
    p2 = getpass.getpass("Confirm admin password: ")
    if p1 != p2:
        print("Passwords do not match.", file=sys.stderr)
        sys.exit(1)
    if not p1:
        print("Password cannot be empty.", file=sys.stderr)
        sys.exit(1)
    print(hash_password(p1))
