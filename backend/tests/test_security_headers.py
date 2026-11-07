"""Tests for SecurityHeadersMiddleware."""

from __future__ import annotations

import unittest

from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.testclient import TestClient

from app.core.middleware import install_security_headers


class TestSecurityHeadersMiddleware(unittest.TestCase):
    def setUp(self) -> None:
        self.app = FastAPI()
        install_security_headers(self.app)

        @self.app.get("/page", response_class=HTMLResponse)
        def html_view() -> str:
            return "<html><body>Kiosk</body></html>"

        @self.app.get("/api/data")
        def api_view() -> dict[str, str]:
            return {"status": "ok"}

        @self.app.get("/api/custom")
        def custom_view() -> JSONResponse:
            return JSONResponse(
                content={"status": "custom"},
                headers={
                    "Cache-Control": "public, max-age=3600",
                    "X-Frame-Options": "SAMEORIGIN",
                },
            )

        @self.app.get("/docs", response_class=HTMLResponse)
        def docs_view() -> str:
            return "<html><body>Swagger docs</body></html>"

        @self.app.websocket("/ws/stream")
        async def ws_view(websocket: WebSocket) -> None:
            await websocket.accept()
            msg = await websocket.receive_text()
            await websocket.send_text(f"echo:{msg}")
            await websocket.close()

        self.client = TestClient(self.app)

    def test_html_response_has_csp_and_security_headers(self) -> None:
        response = self.client.get("/page")
        self.assertEqual(response.status_code, 200)

        # Baseline security headers
        self.assertEqual(response.headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(response.headers.get("x-frame-options"), "DENY")
        self.assertEqual(response.headers.get("referrer-policy"), "same-origin")
        self.assertEqual(
            response.headers.get("permissions-policy"),
            "camera=(self), microphone=(), geolocation=()",
        )
        self.assertEqual(response.headers.get("cross-origin-opener-policy"), "same-origin")

        # HTML response must have CSP
        csp = response.headers.get("content-security-policy")
        self.assertIsNotNone(csp)
        self.assertIn("default-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)

        # Non-API path must not have no-store by default
        self.assertNotEqual(response.headers.get("cache-control"), "no-store")

    def test_api_json_response_has_nosniff_and_no_store_without_csp(self) -> None:
        response = self.client.get("/api/data")
        self.assertEqual(response.status_code, 200)

        # Common headers
        self.assertEqual(response.headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(response.headers.get("x-frame-options"), "DENY")
        self.assertEqual(response.headers.get("referrer-policy"), "same-origin")
        self.assertEqual(
            response.headers.get("permissions-policy"),
            "camera=(self), microphone=(), geolocation=()",
        )
        self.assertEqual(response.headers.get("cross-origin-opener-policy"), "same-origin")

        # /api/ must have Cache-Control: no-store
        self.assertEqual(response.headers.get("cache-control"), "no-store")

        # JSON response must NOT have CSP
        self.assertNotIn("content-security-policy", response.headers)

    def test_swagger_docs_has_no_csp(self) -> None:
        response = self.client.get("/docs")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("content-security-policy", response.headers)

    def test_custom_headers_are_not_overwritten(self) -> None:
        response = self.client.get("/api/custom")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("cache-control"), "public, max-age=3600")
        self.assertEqual(response.headers.get("x-frame-options"), "SAMEORIGIN")

    def test_websocket_works_transparently(self) -> None:
        with self.client.websocket_connect("/ws/stream") as websocket:
            websocket.send_text("ping")
            reply = websocket.receive_text()
            self.assertEqual(reply, "echo:ping")


if __name__ == "__main__":
    unittest.main()
