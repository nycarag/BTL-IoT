"""Security headers middleware implemented as a pure ASGI middleware."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core.config import settings

DEFAULT_SECURITY_CSP = (
    "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
    "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self' ws: wss:; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
)

DOC_PATHS = {"/docs", "/redoc", "/openapi.json"}


class SecurityHeadersMiddleware:
    """Pure ASGI middleware adding standard security headers to HTTP responses."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                raw_headers: list[tuple[bytes, bytes]] = list(message.get("headers", []))
                existing_names = {h[0].lower() for h in raw_headers}

                def add_header(name: bytes, val: bytes) -> None:
                    if name.lower() not in existing_names:
                        raw_headers.append((name, val))
                        existing_names.add(name.lower())

                add_header(b"x-content-type-options", b"nosniff")
                add_header(b"x-frame-options", b"DENY")
                add_header(b"referrer-policy", b"same-origin")
                add_header(b"permissions-policy", b"camera=(self), microphone=(), geolocation=()")
                add_header(b"cross-origin-opener-policy", b"same-origin")

                path: str = scope.get("path", "")
                if path.startswith("/api/") or path == "/api":
                    add_header(b"cache-control", b"no-store")

                # CSP: chỉ thêm khi response là text/html và không thuộc doc paths
                if path not in DOC_PATHS and not any(path.startswith(dp + "/") for dp in DOC_PATHS):
                    content_type = b""
                    for h_name, h_val in raw_headers:
                        if h_name.lower() == b"content-type":
                            content_type = h_val
                            break
                    if b"text/html" in content_type.lower():
                        csp = getattr(settings, "security_csp", DEFAULT_SECURITY_CSP)
                        add_header(b"content-security-policy", csp.encode("latin1"))

                message["headers"] = raw_headers

            await send(message)

        await self.app(scope, receive, send_with_security_headers)


def install_security_headers(app: Any) -> None:
    """Install SecurityHeadersMiddleware onto the application."""
    app.add_middleware(SecurityHeadersMiddleware)
