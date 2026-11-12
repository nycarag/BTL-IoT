from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
import os
import threading
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import (
    attendance,
    audit,
    auth,
    cloud,
    devices,
    export,
    roster_io,
    schedules,
    sessions,
    settings as settings_api,
    students,
    websocket,
)
from app.core.config import ROOT_DIR, settings
from app.core.middleware import install_security_headers
from app.database import init_db
from app.services import cloud_sync
from app.services.auto_session import run_forever
from app.services.bridge_control import bridge
from app.services.face_recognition import prepare_encoder, shutdown_encoder

DEFAULT_DEVICE_TOKEN = "esp32_device_secret_token_ptit"
DEFAULT_ADMIN_PASSWORD = "admin123456"

try:
    from app.core.config import enforce_secure_settings
except ImportError:
    logger = logging.getLogger(__name__)

    def insecure_settings(s: Any) -> list[str]:
        warnings: list[str] = []
        device_token = getattr(s, "device_token", os.getenv("DEVICE_TOKEN", DEFAULT_DEVICE_TOKEN))
        if device_token == DEFAULT_DEVICE_TOKEN or len(device_token) < 16:
            warnings.append("Cảnh báo: DEVICE_TOKEN đang dùng giá trị mặc định hoặc ngắn hơn 16 ký tự.")

        admin_hash = getattr(s, "admin_password_hash", os.getenv("ADMIN_PASSWORD_HASH", ""))
        admin_pass = getattr(s, "admin_password", os.getenv("ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD))
        if not admin_hash and (admin_pass == DEFAULT_ADMIN_PASSWORD or len(admin_pass) < 10):
            warnings.append("Cảnh báo: ADMIN_PASSWORD đang dùng mật khẩu mặc định hoặc ngắn hơn 10 ký tự.")

        secret_key_env = os.getenv("SECRET_KEY", "").strip()
        if not secret_key_env or len(secret_key_env) < 32:
            warnings.append("Cảnh báo: SECRET_KEY trong biến môi trường không được đặt hoặc ngắn hơn 32 ký tự.")

        app_env = getattr(s, "app_env", os.getenv("APP_ENV", "development")).lower().strip()
        docs_enabled = _is_docs_enabled()
        if app_env == "production" and docs_enabled:
            warnings.append("Cảnh báo: enable_api_docs không được bật khi app_env == production.")

        return warnings

    def enforce_secure_settings(s: Any) -> None:
        warnings = insecure_settings(s)
        app_env = getattr(s, "app_env", os.getenv("APP_ENV", "development")).lower().strip()
        if app_env == "production":
            if warnings:
                raise RuntimeError("Cấu hình không an toàn cho production:\n" + "\n".join(warnings))
        else:
            for w in warnings:
                logger.warning(w)


def _is_docs_enabled() -> bool:
    if hasattr(settings, "enable_api_docs"):
        return bool(settings.enable_api_docs)
    env_docs = os.getenv("ENABLE_API_DOCS")
    app_env = getattr(settings, "app_env", os.getenv("APP_ENV", "development")).lower().strip()
    if env_docs is not None:
        return env_docs.lower().strip() in ("1", "true", "yes", "on")
    return app_env != "production"


def create_app() -> FastAPI:
    enforce_secure_settings(settings)

    docs_enabled = _is_docs_enabled()

    @asynccontextmanager
    async def lifespan(application):
        init_db()
        if settings.recognition_process:
            # Tiến trình con trích vector mất vài giây để nạp dlib. Khởi động từ lúc bật app,
            # trong luồng riêng, để sinh viên đầu tiên của ca không phải chờ.
            threading.Thread(target=lambda: prepare_encoder(attendance._recognizer()), daemon=True).start()
        task = None
        if settings.auto_session_enabled:
            task = asyncio.create_task(run_forever())
        cloud_task = None
        if settings.cloud_sync_url:
            cloud_task = asyncio.create_task(cloud_sync.run_forever())
        try:
            yield
        finally:
            if cloud_task:
                cloud_task.cancel()
                try:
                    await cloud_task
                except asyncio.CancelledError:
                    pass
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            shutdown_encoder()
            bridge.stop()

    application = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_origin_regex=settings.cors_origin_regex or None,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_security_headers(application)

    application.include_router(auth.router, prefix="/api")
    application.include_router(roster_io.router, prefix="/api")
    application.include_router(students.router, prefix="/api")
    application.include_router(schedules.router, prefix="/api")
    application.include_router(sessions.router, prefix="/api")
    application.include_router(devices.router, prefix="/api")
    application.include_router(attendance.router, prefix="/api")
    application.include_router(export.router, prefix="/api")
    application.include_router(audit.router, prefix="/api")
    application.include_router(settings_api.router, prefix="/api")
    application.include_router(cloud.router, prefix="/api")
    application.include_router(websocket.router)

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    frontend_dist = ROOT_DIR / "frontend" / "dist"
    if frontend_dist.is_dir():
        application.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return application


app = create_app()
