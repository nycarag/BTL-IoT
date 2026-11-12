"""Đồng bộ dữ liệu điểm danh và thiết bị từ Gateway lên Cloud (Google Sheets)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
import socket
import threading
import urllib.error
import urllib.request
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.database import SessionLocal
from app.models.school import AppSetting, Attendance, AttendanceSession, Device, Student

logger = logging.getLogger(__name__)
VN_TZ = timezone(timedelta(hours=7))

_lock = threading.Lock()
_state: dict[str, Any] = {"last_ok_at": None, "last_error": None, "sent_total": 0, "cursor": 0, "pending": 0}


def _format_vn_time(dt: datetime | None) -> str:
    if dt is None:
        return ""
    dt_utc = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    return dt_utc.astimezone(VN_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _sanitize_error(msg: str, url: str | None = None, token: str | None = None) -> str:
    cleaned = str(msg)
    for s in (url, token, settings.cloud_sync_url, settings.cloud_sync_token):
        if s and s.strip() and s.strip() in cleaned:
            cleaned = cleaned.replace(s.strip(), "<redacted>")
    return cleaned


def collect_attendance(db: Session, after_id: int, gateway_id: str, limit: int = 200) -> list[dict]:
    query = (
        select(Attendance)
        .options(
            joinedload(Attendance.student).joinedload(Student.classroom),
            joinedload(Attendance.session).joinedload(AttendanceSession.classroom),
        )
        .where(Attendance.id > after_id)
        .order_by(Attendance.id.asc())
        .limit(limit)
    )
    results = []
    for att in db.scalars(query).all():
        c_code = (att.session.classroom.code if att.session and att.session.classroom
                  else (att.student.classroom.code if att.student and att.student.classroom else ""))
        results.append({
            "event_id": f"{gateway_id}-att-{att.id}", "checked_at": _format_vn_time(att.checked_at),
            "student_code": att.student.student_code if att.student else "",
            "student_name": att.student.name if att.student else "", "class_code": c_code,
            "session_id": att.session_id, "session_title": att.session.title if att.session else "",
            "status": att.status, "device_id": att.device_id or "",
            "verification": att.verification or "", "_id": att.id,
        })
    return results


def device_snapshot(db: Session) -> list[dict]:
    now = datetime.now(timezone.utc)
    results = []
    for d in db.scalars(select(Device).order_by(Device.id)).all():
        last = d.last_seen.replace(tzinfo=timezone.utc) if d.last_seen.tzinfo is None else d.last_seen.astimezone(timezone.utc)
        st = "online" if (now - last).total_seconds() <= settings.device_offline_seconds else "offline"
        results.append({"device_id": str(d.id), "name": d.name, "status": st, "last_seen": _format_vn_time(d.last_seen)})
    return results


def post_json(url: str, payload: dict, timeout: float = 15.0) -> dict:
    if not (url.startswith("https://") or url.startswith("http://127.0.0.1") or url.startswith("http://localhost")):
        raise ValueError("Chỉ cho phép URL bắt đầu bằng https:// hoặc http://127.0.0.1 / http://localhost")
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} {exc.reason}") from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout, json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"Lỗi mạng: {exc}") from exc


def sync_once(url: str | None = None, token: str | None = None, backfill: bool | None = None) -> dict:
    effective_url = settings.cloud_sync_url if url is None else url
    effective_token = settings.cloud_sync_token if token is None else token
    effective_backfill = settings.cloud_sync_backfill if backfill is None else backfill
    gateway_id = settings.gateway_id

    if not effective_url or not effective_url.strip():
        return {"enabled": False}

    cursor, pending = 0, 0
    try:
        with SessionLocal() as db:
            setting = db.get(AppSetting, "cloud_last_attendance_id")
            if setting is not None:
                try:
                    cursor = int(setting.value)
                except (ValueError, TypeError):
                    cursor = 0
            elif effective_backfill:
                cursor = 0
            else:
                max_id = db.scalar(select(func.max(Attendance.id)))
                cursor = int(max_id) if max_id is not None else 0

            batch = collect_attendance(db, after_id=cursor, gateway_id=gateway_id, limit=200)
            devices = device_snapshot(db)
            pending = db.scalar(select(func.count(Attendance.id)).where(Attendance.id > cursor)) or 0

        payload = {
            "token": effective_token, "gateway_id": gateway_id,
            "attendance": [{k: v for k, v in r.items() if k != "_id"} for r in batch],
            "devices": devices, "command_results": [],
        }

        resp_data = post_json(effective_url, payload)
        if not resp_data.get("ok"):
            raise RuntimeError(str(resp_data.get("error", "token")))

        new_cursor = max((r["_id"] for r in batch), default=cursor)
        with SessionLocal() as db:
            setting = db.get(AppSetting, "cloud_last_attendance_id")
            now_utc = datetime.now(timezone.utc)
            if setting is None:
                db.add(AppSetting(key="cloud_last_attendance_id", value=str(new_cursor), updated_at=now_utc))
            else:
                setting.value, setting.updated_at = str(new_cursor), now_utc
            db.commit()
            pending = db.scalar(select(func.count(Attendance.id)).where(Attendance.id > new_cursor)) or 0

        with _lock:
            _state["cursor"] = new_cursor
            _state["pending"] = pending
            _state["sent_total"] += len(batch)
            _state["last_ok_at"] = _format_vn_time(datetime.now(timezone.utc))
            _state["last_error"] = None

        return {
            "enabled": True, "ok": True, "sent": len(batch),
            "added": int(resp_data.get("added", 0)), "pending": pending,
            "commands": resp_data.get("commands", []),
        }
    except Exception as exc:
        err_msg = _sanitize_error(str(exc), effective_url, effective_token)
        logger.warning("Cloud sync warning: %s", err_msg)
        with _lock:
            _state["cursor"] = cursor
            _state["pending"] = pending
            _state["last_error"] = err_msg
        return {"enabled": True, "ok": False, "sent": 0, "added": 0, "pending": pending, "commands": []}


def status() -> dict:
    with _lock:
        return {
            "enabled": bool(settings.cloud_sync_url), "gateway_id": settings.gateway_id,
            "interval_seconds": settings.cloud_sync_interval_seconds, "last_ok_at": _state["last_ok_at"],
            "last_error": _state["last_error"], "sent_total": _state["sent_total"],
            "cursor": _state["cursor"], "pending": _state["pending"],
        }


async def run_forever() -> None:
    limit = 200
    while True:
        try:
            res = await asyncio.to_thread(sync_once)
            if not res.get("enabled", True):
                await asyncio.sleep(settings.cloud_sync_interval_seconds)
                continue
            if res.get("ok") and res.get("sent", 0) >= limit:
                continue
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Lỗi không mong muốn trong vòng lặp cloud_sync")

        try:
            await asyncio.sleep(settings.cloud_sync_interval_seconds)
        except asyncio.CancelledError:
            raise
