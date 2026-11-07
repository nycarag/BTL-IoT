"""API endpoints for class schedules (CRUD, import, export, create-session)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import re
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import verify_token
from app.database import get_db
from app.models.school import AttendanceSession, ClassRoom, ClassSchedule
from app.schemas.api import SessionResponse
from app.schemas.roster_io import ImportError as ScheduleImportError, ImportResult
from app.schemas.schedule import ScheduleInput, ScheduleResponse
from app.services import ics, tabular
from app.services.audit import client_ip, log_action
from app.services.tabular import normalize_header

router = APIRouter()

VN_TZ = timezone(timedelta(hours=7), "ICT")
MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MiB

SCHEDULE_HEADER_MAP: dict[str, set[str]] = {
    "class_code": {"ma_lop", "lop", "class_code"},
    "title": {"ten_buoi", "mon_hoc", "mon", "tieu_de", "title"},
    "date": {"ngay", "ngay_hoc", "date"},
    "start_time": {"bat_dau", "gio_bat_dau", "tu", "start"},
    "end_time": {"ket_thuc", "gio_ket_thuc", "den", "end"},
    "room": {"phong", "phong_hoc", "room"},
    "note": {"ghi_chu", "note"},
}


def _to_utc(date_str: str, time_str: str) -> datetime:
    """Chuyển ngày YYYY-MM-DD và giờ HH:MM (giờ VN) sang datetime UTC aware."""
    d = date.fromisoformat(date_str)
    parts = time_str.split(":")
    t = time(int(parts[0]), int(parts[1]))
    dt_vn = datetime.combine(d, t, tzinfo=VN_TZ)
    return dt_vn.astimezone(timezone.utc)


def _to_vn(dt: datetime) -> datetime:
    """Chuyển datetime (nếu naive coi là UTC) sang datetime aware múi giờ VN."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(VN_TZ)


def _parse_time_string(raw: str) -> tuple[int, int] | None:
    """Nhận diện giờ dạng H:MM, HH:MM, 7h, 7h30, 07h, 07h30, 14H, 14H00."""
    s = raw.strip()
    if not s:
        return None
    # 1. H:MM or HH:MM or HH:MM:SS
    m_colon = re.match(r"^(\d{1,2}):(\d{1,2})(?::\d{1,2})?$", s)
    if m_colon:
        h, m = int(m_colon.group(1)), int(m_colon.group(2))
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h, m
        return None
    # 2. 7h, 7h30, 07h, 07h30, 14H, 14H00
    m_h = re.match(r"^(\d{1,2})[hH](\d{1,2})?$", s)
    if m_h:
        h = int(m_h.group(1))
        m = int(m_h.group(2) or 0)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h, m
        return None
    return None


def _parse_date_string(raw: str) -> date | None:
    """Nhận diện ngày dd/mm/yyyy, d/m/yyyy, yyyy-mm-dd, dd-mm-yyyy."""
    s = raw.strip()
    if not s:
        return None
    m_slash = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m_slash:
        d, m, y = int(m_slash.group(1)), int(m_slash.group(2)), int(m_slash.group(3))
        try:
            return date(y, m, d)
        except ValueError:
            return None

    m_dash = re.match(r"^(\d{1,2})-(\d{1,2})-(\d{4})$", s)
    if m_dash:
        d, m, y = int(m_dash.group(1)), int(m_dash.group(2)), int(m_dash.group(3))
        try:
            return date(y, m, d)
        except ValueError:
            return None

    m_iso = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if m_iso:
        y, m, d = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
        try:
            return date(y, m, d)
        except ValueError:
            return None

    return None


def _build_schedule_response(
    schedule: ClassSchedule,
    class_code: str,
    session_status: str | None = None,
) -> ScheduleResponse:
    start_vn = _to_vn(schedule.start_at)
    end_vn = _to_vn(schedule.end_at)
    return ScheduleResponse(
        id=schedule.id,
        class_id=schedule.class_id,
        class_code=class_code,
        title=schedule.title,
        date=start_vn.strftime("%Y-%m-%d"),
        start_time=start_vn.strftime("%H:%M"),
        end_time=end_vn.strftime("%H:%M"),
        room=schedule.room,
        note=schedule.note,
        session_id=schedule.session_id,
        session_status=session_status,
    )


@router.get("/schedules", response_model=list[ScheduleResponse])
def list_schedules(
    class_id: int | None = Query(None),
    date_from: str | None = Query(None, description="Từ ngày (YYYY-MM-DD giờ VN)"),
    date_to: str | None = Query(None, description="Đến ngày (YYYY-MM-DD giờ VN)"),
    username: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    stmt = (
        select(ClassSchedule, ClassRoom.code, AttendanceSession.status)
        .join(ClassRoom, ClassSchedule.class_id == ClassRoom.id)
        .outerjoin(AttendanceSession, ClassSchedule.session_id == AttendanceSession.id)
        .order_by(ClassSchedule.start_at.asc())
    )

    if class_id is not None:
        stmt = stmt.where(ClassSchedule.class_id == class_id)

    if date_from:
        start_utc_min = _to_utc(date_from, "00:00")
        stmt = stmt.where(ClassSchedule.start_at >= start_utc_min)

    if date_to:
        d_to = date.fromisoformat(date_to)
        next_day = (d_to + timedelta(days=1)).isoformat()
        end_utc_max = _to_utc(next_day, "00:00")
        stmt = stmt.where(ClassSchedule.start_at < end_utc_max)

    results = db.execute(stmt).all()
    return [_build_schedule_response(s, c_code, sess_status) for s, c_code, sess_status in results]


@router.post("/schedules", response_model=ScheduleResponse, status_code=status.HTTP_201_CREATED)
def create_schedule(
    payload: ScheduleInput,
    request: Request,
    username: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    classroom = db.get(ClassRoom, payload.class_id)
    if not classroom:
        raise HTTPException(404, "Không tìm thấy lớp")

    start_at_utc = _to_utc(payload.date, payload.start_time)
    end_at_utc = _to_utc(payload.date, payload.end_time)

    # Check conflicts for the same class
    existing_schedules = db.scalars(
        select(ClassSchedule).where(ClassSchedule.class_id == payload.class_id)
    ).all()

    for other in existing_schedules:
        other_start = other.start_at.replace(tzinfo=timezone.utc) if other.start_at.tzinfo is None else other.start_at
        other_end = other.end_at.replace(tzinfo=timezone.utc) if other.end_at.tzinfo is None else other.end_at

        if other_start == start_at_utc:
            raise HTTPException(409, f"Lớp đã có lịch bắt đầu lúc {payload.start_time}")

        if start_at_utc < other_end and end_at_utc > other_start:
            raise HTTPException(409, f"Trùng giờ với lịch #{other.id}")

    schedule = ClassSchedule(
        class_id=payload.class_id,
        title=payload.title,
        start_at=start_at_utc,
        end_at=end_at_utc,
        room=payload.room,
        note=payload.note,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)

    log_action(
        db,
        username,
        "schedules.create",
        target=f"schedule:{schedule.id}",
        detail={
            "class_id": schedule.class_id,
            "title": schedule.title,
            "date": payload.date,
            "start_time": payload.start_time,
            "end_time": payload.end_time,
        },
        ip_address=client_ip(request),
    )

    return _build_schedule_response(schedule, classroom.code)


@router.put("/schedules/{id}", response_model=ScheduleResponse)
def update_schedule(
    id: int,
    payload: ScheduleInput,
    request: Request,
    username: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    schedule = db.get(ClassSchedule, id)
    if not schedule:
        raise HTTPException(404, "Không tìm thấy lịch học")

    classroom = db.get(ClassRoom, payload.class_id)
    if not classroom:
        raise HTTPException(404, "Không tìm thấy lớp")

    # If linked to session, verify session is draft
    if schedule.session_id:
        sess = db.get(AttendanceSession, schedule.session_id)
        if sess and sess.status != "draft":
            raise HTTPException(409, "Buổi điểm danh đã mở/đóng, không sửa lịch được")

    start_at_utc = _to_utc(payload.date, payload.start_time)
    end_at_utc = _to_utc(payload.date, payload.end_time)

    # Check conflict with other schedules of same class
    existing_schedules = db.scalars(
        select(ClassSchedule).where(
            ClassSchedule.class_id == payload.class_id,
            ClassSchedule.id != id,
        )
    ).all()

    for other in existing_schedules:
        other_start = other.start_at.replace(tzinfo=timezone.utc) if other.start_at.tzinfo is None else other.start_at
        other_end = other.end_at.replace(tzinfo=timezone.utc) if other.end_at.tzinfo is None else other.end_at

        if other_start == start_at_utc:
            raise HTTPException(409, f"Lớp đã có lịch bắt đầu lúc {payload.start_time}")

        if start_at_utc < other_end and end_at_utc > other_start:
            raise HTTPException(409, f"Trùng giờ với lịch #{other.id}")

    schedule.class_id = payload.class_id
    schedule.title = payload.title
    schedule.start_at = start_at_utc
    schedule.end_at = end_at_utc
    schedule.room = payload.room
    schedule.note = payload.note
    db.commit()
    db.refresh(schedule)

    session_status = None
    if schedule.session_id:
        sess = db.get(AttendanceSession, schedule.session_id)
        session_status = sess.status if sess else None

    log_action(
        db,
        username,
        "schedules.update",
        target=f"schedule:{id}",
        detail={
            "class_id": schedule.class_id,
            "title": schedule.title,
            "date": payload.date,
            "start_time": payload.start_time,
            "end_time": payload.end_time,
        },
        ip_address=client_ip(request),
    )

    return _build_schedule_response(schedule, classroom.code, session_status)


@router.delete("/schedules/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule(
    id: int,
    request: Request,
    username: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    schedule = db.get(ClassSchedule, id)
    if not schedule:
        raise HTTPException(404, "Không tìm thấy lịch học")

    if schedule.session_id:
        sess = db.get(AttendanceSession, schedule.session_id)
        if sess and sess.status != "draft":
            raise HTTPException(409, "Buổi điểm danh đã mở/đóng, không sửa lịch được")
        if sess and sess.status == "draft":
            schedule.session_id = None
            db.flush()

    db.delete(schedule)
    db.commit()

    log_action(
        db,
        username,
        "schedules.delete",
        target=f"schedule:{id}",
        ip_address=client_ip(request),
    )


@router.post("/schedules/{id}/create-session", response_model=SessionResponse)
def create_schedule_session(
    id: int,
    response: Response,
    request: Request,
    username: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    schedule = db.get(ClassSchedule, id)
    if not schedule:
        raise HTTPException(404, "Không tìm thấy lịch học")

    if schedule.session_id:
        existing = db.get(AttendanceSession, schedule.session_id)
        if existing:
            response.status_code = status.HTTP_200_OK
            return existing

    start_vn = _to_vn(schedule.start_at)
    date_str = start_vn.strftime("%d/%m/%Y")
    session_title = f"{schedule.title} · {date_str}"

    new_sess = AttendanceSession(
        class_id=schedule.class_id,
        title=session_title,
        status="draft",
    )
    db.add(new_sess)
    db.flush()
    schedule.session_id = new_sess.id
    db.commit()
    db.refresh(new_sess)

    log_action(
        db,
        username,
        "schedules.create_session",
        target=f"schedule:{id}",
        detail={"session_id": new_sess.id},
        ip_address=client_ip(request),
    )

    response.status_code = status.HTTP_201_CREATED
    return new_sess


@router.get("/schedules/export")
def export_schedules(
    request: Request,
    format: str = Query(..., description="Định dạng xuất: csv, xlsx hoặc ics"),
    class_id: int | None = Query(None, description="Lọc theo lớp"),
    date_from: str | None = Query(None, description="Từ ngày (YYYY-MM-DD giờ VN)"),
    date_to: str | None = Query(None, description="Đến ngày (YYYY-MM-DD giờ VN)"),
    username: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    fmt = format.lower().strip()
    if fmt not in {"csv", "xlsx", "ics"}:
        raise HTTPException(422, "Định dạng không được hỗ trợ (chỉ chấp nhận csv, xlsx hoặc ics)")

    class_code_str = "tat_ca"
    if class_id is not None:
        classroom = db.get(ClassRoom, class_id)
        if not classroom:
            raise HTTPException(404, "Không tìm thấy lớp")
        class_code_str = classroom.code

    stmt = (
        select(ClassSchedule, ClassRoom.code, AttendanceSession.status)
        .join(ClassRoom, ClassSchedule.class_id == ClassRoom.id)
        .outerjoin(AttendanceSession, ClassSchedule.session_id == AttendanceSession.id)
        .order_by(ClassSchedule.start_at.asc())
    )

    if class_id is not None:
        stmt = stmt.where(ClassSchedule.class_id == class_id)

    if date_from:
        start_utc_min = _to_utc(date_from, "00:00")
        stmt = stmt.where(ClassSchedule.start_at >= start_utc_min)

    if date_to:
        d_to = date.fromisoformat(date_to)
        next_day = (d_to + timedelta(days=1)).isoformat()
        end_utc_max = _to_utc(next_day, "00:00")
        stmt = stmt.where(ClassSchedule.start_at < end_utc_max)

    records = db.execute(stmt).all()

    now_vn = datetime.now(timezone.utc).astimezone(VN_TZ)
    timestamp = now_vn.strftime("%Y%m%d")
    filename = f"lich_hoc_{class_code_str}_{timestamp}.{fmt}"

    if fmt in {"csv", "xlsx"}:
        headers = [
            "Mã lớp",
            "Tên buổi",
            "Ngày (dd/mm/yyyy)",
            "Bắt đầu (HH:MM)",
            "Kết thúc (HH:MM)",
            "Phòng",
            "Ghi chú",
            "Mã buổi điểm danh",
        ]
        rows: list[list[object]] = []
        for s, c_code, _ in records:
            start_vn = _to_vn(s.start_at)
            end_vn = _to_vn(s.end_at)
            rows.append(
                [
                    c_code or "",
                    s.title,
                    start_vn.strftime("%d/%m/%Y"),
                    start_vn.strftime("%H:%M"),
                    end_vn.strftime("%H:%M"),
                    s.room or "",
                    s.note or "",
                    s.session_id if s.session_id is not None else "",
                ]
            )

        if fmt == "csv":
            content = tabular.write_csv(headers, rows)
            media_type = "text/csv; charset=utf-8"
        else:
            content = tabular.write_xlsx(headers, rows, sheet_name="LichHoc")
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        events = []
        for s, c_code, _ in records:
            start_vn = _to_vn(s.start_at)
            end_vn = _to_vn(s.end_at)
            events.append(
                {
                    "uid": f"schedule-{s.id}@btl-iot.local",
                    "title": f"[{c_code}] {s.title}",
                    "start_at": start_vn,
                    "end_at": end_vn,
                    "location": s.room,
                    "description": s.note,
                }
            )
        content = ics.build_calendar(events, calendar_name=f"Lich hoc {class_code_str}")
        media_type = "text/calendar; charset=utf-8"

    log_action(
        db,
        username,
        "schedules.export",
        detail={"format": fmt, "class_id": class_id, "count": len(records)},
        ip_address=client_ip(request),
    )

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/schedules/import-template")
def get_import_template(
    format: str = Query(..., description="Định dạng mẫu: csv hoặc xlsx"),
):
    fmt = format.lower().strip()
    if fmt not in {"csv", "xlsx"}:
        raise HTTPException(422, "Định dạng không được hỗ trợ (chỉ chấp nhận csv hoặc xlsx)")

    headers = [
        "Mã lớp",
        "Tên buổi",
        "Ngày (dd/mm/yyyy)",
        "Bắt đầu (HH:MM)",
        "Kết thúc (HH:MM)",
        "Phòng",
        "Ghi chú",
    ]
    rows: list[list[object]] = [
        ["D23CTAT01-B", "IoT và ứng dụng", "10/11/2026", "07:00", "09:00", "402-A2", "Buổi 1"],
        ["D23CTAT01-B", "IoT và ứng dụng", "17/11/2026", "07:00", "09:00", "402-A2", "Buổi 2"],
    ]

    filename = f"mau_nhap_lich_hoc.{fmt}"
    if fmt == "csv":
        content = tabular.write_csv(headers, rows)
        media_type = "text/csv; charset=utf-8"
    else:
        content = tabular.write_xlsx(headers, rows, sheet_name="MauLichHoc")
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/schedules/import", response_model=ImportResult)
async def import_schedules(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Form("preview"),
    on_conflict: str = Form("skip"),
    class_id: int | None = Form(None),
    username: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    if mode not in {"preview", "commit"}:
        raise HTTPException(422, "Chế độ (mode) không hợp lệ, chỉ chấp nhận preview hoặc commit")
    if on_conflict not in {"skip", "update"}:
        raise HTTPException(422, "on_conflict không hợp lệ, chỉ chấp nhận skip hoặc update")

    filename = file.filename or ""
    ext = Path(filename).suffix.lower()
    if ext not in {".csv", ".xlsx", ".ics"}:
        raise HTTPException(415, "Định dạng tệp không được hỗ trợ. Chỉ chấp nhận .csv, .xlsx, .ics")

    body = await file.read(MAX_FILE_BYTES + 1)
    if len(body) > MAX_FILE_BYTES:
        raise HTTPException(413, "Tệp vượt quá kích thước tối đa 2 MiB")

    raw_items: list[dict[str, Any]] = []

    # Map existing classes by code
    classes_by_code: dict[str, ClassRoom] = {c.code.upper(): c for c in db.scalars(select(ClassRoom))}

    if ext == ".ics":
        if not class_id:
            raise HTTPException(422, "Tệp .ics cần chọn lớp")
        selected_class = db.get(ClassRoom, class_id)
        if not selected_class:
            raise HTTPException(404, "Không tìm thấy lớp")

        try:
            events = ics.parse_calendar(body, max_events=1000)
        except ics.IcsError as exc:
            raise HTTPException(422, str(exc))

        if not events:
            raise HTTPException(422, "Tệp không có dữ liệu")

        for event in events:
            title_clean = event["title"].strip()
            # If title is in [CODE] Title format, extract Title
            m_title = re.match(r"^\[.*?\]\s*(.*)$", title_clean)
            if m_title and m_title.group(1):
                title_clean = m_title.group(1).strip()

            start_vn = event["start_at"]
            end_vn = event["end_at"]

            raw_items.append(
                {
                    "__row__": event["row"],
                    "class_code": selected_class.code,
                    "title": title_clean,
                    "date": start_vn.strftime("%Y-%m-%d"),
                    "start_time": start_vn.strftime("%H:%M"),
                    "end_time": end_vn.strftime("%H:%M"),
                    "room": event.get("location") or "",
                    "note": event.get("description") or "",
                    "parsed_start_dt": start_vn,
                    "parsed_end_dt": end_vn,
                }
            )

    else:  # .csv, .xlsx
        try:
            headers, raw_table = tabular.read_table(filename, body, max_rows=1000)
        except tabular.TabularError as exc:
            raise HTTPException(422, str(exc))

        col_map: dict[str, str] = {}
        for h in headers:
            for field, aliases in SCHEDULE_HEADER_MAP.items():
                if h in aliases and field not in col_map:
                    col_map[field] = h
                    break

        # Check required fields
        if "class_code" not in col_map and not class_id:
            err = ScheduleImportError(
                row=1,
                field="class_code",
                message="Tệp thiếu cột mã lớp và không chọn lớp trong biểu mẫu",
            )
            return JSONResponse(
                status_code=422,
                content=ImportResult(
                    mode=mode, total_rows=0, valid_rows=0, created=0, updated=0, skipped=0,
                    errors=[err], rows=[]
                ).model_dump(),
            )

        form_class_obj = None
        if class_id:
            form_class_obj = db.get(ClassRoom, class_id)
            if not form_class_obj:
                raise HTTPException(404, "Không tìm thấy lớp")

        required_fields = ["title", "date", "start_time", "end_time"]
        for rf in required_fields:
            if rf not in col_map:
                err = ScheduleImportError(row=1, field=rf, message=f"Thiếu cột bắt buộc: {rf}")
                return JSONResponse(
                    status_code=422,
                    content=ImportResult(
                        mode=mode, total_rows=0, valid_rows=0, created=0, updated=0, skipped=0,
                        errors=[err], rows=[]
                    ).model_dump(),
                )

        for r in raw_table:
            row_dict = {"__row__": r["__row__"]}
            for field in SCHEDULE_HEADER_MAP:
                col_name = col_map.get(field)
                val = str(r.get(col_name) or "").strip() if col_name else ""
                row_dict[field] = val
            if not row_dict.get("class_code") and form_class_obj:
                row_dict["class_code"] = form_class_obj.code
            raw_items.append(row_dict)

    # Validate each row and collect ALL errors
    errors: list[ScheduleImportError] = []
    processed_rows: list[dict[str, Any]] = []

    # Track in-file intervals per class to catch duplicates and overlaps: class_id -> list[(start_utc, end_utc, row_num)]
    file_intervals_by_class: dict[int, list[tuple[datetime, datetime, int]]] = {}

    created = 0
    updated = 0
    skipped = 0

    # Load existing schedules from DB per class
    db_schedules_by_class: dict[int, list[ClassSchedule]] = {}
    for sched in db.scalars(select(ClassSchedule)):
        db_schedules_by_class.setdefault(sched.class_id, []).append(sched)

    for item in raw_items:
        row_num = item["__row__"]
        row_errors: list[ScheduleImportError] = []

        # 1. class_code
        c_code_raw = str(item.get("class_code") or "").strip()
        matched_class: ClassRoom | None = None
        if not c_code_raw:
            row_errors.append(
                ScheduleImportError(row=row_num, field="class_code", message="Mã lớp không được để trống")
            )
        else:
            matched_class = classes_by_code.get(c_code_raw.upper())
            if not matched_class:
                row_errors.append(
                    ScheduleImportError(row=row_num, field="class_code", message=f"Lớp '{c_code_raw}' không tồn tại")
                )

        # 2. title
        title_raw = str(item.get("title") or "").strip()
        if not title_raw or len(title_raw) > 255:
            row_errors.append(
                ScheduleImportError(row=row_num, field="title", message="Tên buổi bắt buộc, từ 1 đến 255 ký tự")
            )

        # 3. date & times
        parsed_d = None
        t_start = None
        t_end = None
        start_utc = None
        end_utc = None

        if "parsed_start_dt" in item and "parsed_end_dt" in item:
            dt_s_vn = item["parsed_start_dt"]
            dt_e_vn = item["parsed_end_dt"]
            parsed_d = dt_s_vn.date()
            t_start = (dt_s_vn.hour, dt_s_vn.minute)
            t_end = (dt_e_vn.hour, dt_e_vn.minute)
            start_utc = dt_s_vn.astimezone(timezone.utc)
            end_utc = dt_e_vn.astimezone(timezone.utc)
        else:
            date_raw = str(item.get("date") or "")
            parsed_d = _parse_date_string(date_raw)
            if not parsed_d:
                row_errors.append(
                    ScheduleImportError(
                        row=row_num,
                        field="date",
                        message="Ngày không đúng định dạng (hỗ trợ dd/mm/yyyy, yyyy-mm-dd) hoặc ngày không tồn tại",
                    )
                )

            start_raw = str(item.get("start_time") or "")
            t_start = _parse_time_string(start_raw)
            if not t_start:
                row_errors.append(
                    ScheduleImportError(
                        row=row_num,
                        field="start_time",
                        message=f"Giờ bắt đầu '{start_raw}' không hợp lệ",
                    )
                )

            end_raw = str(item.get("end_time") or "")
            t_end = _parse_time_string(end_raw)
            if not t_end:
                row_errors.append(
                    ScheduleImportError(
                        row=row_num,
                        field="end_time",
                        message=f"Giờ kết thúc '{end_raw}' không hợp lệ",
                    )
                )

            if parsed_d and t_start and t_end:
                dt_start_vn = datetime(parsed_d.year, parsed_d.month, parsed_d.day, t_start[0], t_start[1], tzinfo=VN_TZ)
                dt_end_vn = datetime(parsed_d.year, parsed_d.month, parsed_d.day, t_end[0], t_end[1], tzinfo=VN_TZ)

                if dt_end_vn <= dt_start_vn:
                    row_errors.append(
                        ScheduleImportError(
                            row=row_num,
                            field="end_time",
                            message="Giờ kết thúc phải sau giờ bắt đầu",
                        )
                    )
                elif dt_end_vn - dt_start_vn > timedelta(hours=6):
                    row_errors.append(
                        ScheduleImportError(
                            row=row_num,
                            field="end_time",
                            message="Thời lượng buổi học không được vượt quá 6 giờ",
                        )
                    )
                else:
                    start_utc = dt_start_vn.astimezone(timezone.utc)
                    end_utc = dt_end_vn.astimezone(timezone.utc)

        # 4. in-file conflict check
        if matched_class and start_utc and end_utc:
            cid = matched_class.id
            class_intervals = file_intervals_by_class.setdefault(cid, [])

            has_file_conflict = False
            for p_start, p_end, p_row in class_intervals:
                if p_start == start_utc:
                    row_errors.append(
                        ScheduleImportError(
                            row=row_num,
                            field="start_time",
                            message=f"Trùng lịch với dòng {p_row}",
                        )
                    )
                    has_file_conflict = True
                    break
                elif start_utc < p_end and end_utc > p_start:
                    row_errors.append(
                        ScheduleImportError(
                            row=row_num,
                            field="start_time",
                            message=f"Chồng giờ với dòng {p_row}",
                        )
                    )
                    has_file_conflict = True
                    break

            if not has_file_conflict:
                class_intervals.append((start_utc, end_utc, row_num))

        errors.extend(row_errors)

        action = "error"
        existing_sched_to_update = None

        if not row_errors and matched_class and start_utc and end_utc:
            cid = matched_class.id
            db_schedules = db_schedules_by_class.get(cid, [])

            # Check if exact start_at exists in DB
            match_exact = next(
                (
                    s for s in db_schedules
                    if (s.start_at.replace(tzinfo=timezone.utc) if s.start_at.tzinfo is None else s.start_at) == start_utc
                ),
                None,
            )

            if match_exact:
                if on_conflict == "update":
                    has_session_err = False
                    if match_exact.session_id:
                        sess = db.get(AttendanceSession, match_exact.session_id)
                        if sess and sess.status != "draft":
                            errors.append(
                                ScheduleImportError(
                                    row=row_num,
                                    field="title",
                                    message="Lịch học đã liên kết buổi điểm danh đã mở/đóng, không sửa lịch được",
                                )
                            )
                            has_session_err = True
                    if not has_session_err:
                        action = "update"
                        updated += 1
                        existing_sched_to_update = match_exact
                else:
                    action = "skip"
                    skipped += 1
            else:
                # Check overlap with other schedules in DB
                has_db_overlap = False
                for other in db_schedules:
                    o_start = other.start_at.replace(tzinfo=timezone.utc) if other.start_at.tzinfo is None else other.start_at
                    o_end = other.end_at.replace(tzinfo=timezone.utc) if other.end_at.tzinfo is None else other.end_at
                    if start_utc < o_end and end_utc > o_start:
                        errors.append(
                            ScheduleImportError(
                                row=row_num,
                                field="start_time",
                                message=f"Trùng giờ với lịch #{other.id} trong cơ sở dữ liệu",
                            )
                        )
                        has_db_overlap = True
                        action = "error"
                        break

                if not has_db_overlap:
                    action = "create"
                    created += 1

        processed_rows.append(
            {
                "row": row_num,
                "class_code": c_code_raw,
                "class_id": matched_class.id if matched_class else None,
                "title": title_raw,
                "date": parsed_d.isoformat() if parsed_d else str(item.get("date") or ""),
                "start_time": f"{t_start[0]:02d}:{t_start[1]:02d}" if t_start else str(item.get("start_time") or ""),
                "end_time": f"{t_end[0]:02d}:{t_end[1]:02d}" if t_end else str(item.get("end_time") or ""),
                "room": str(item.get("room") or "").strip() or None,
                "note": str(item.get("note") or "").strip() or None,
                "start_utc": start_utc,
                "end_utc": end_utc,
                "action": action,
                "existing_schedule": existing_sched_to_update,
            }
        )

    total_rows = len(raw_items)
    valid_rows = created + updated + skipped
    preview_rows = [
        {
            "row": r["row"],
            "class_code": r["class_code"],
            "title": r["title"],
            "date": r["date"],
            "start_time": r["start_time"],
            "end_time": r["end_time"],
            "room": r["room"],
            "action": r["action"],
        }
        for r in processed_rows[:50]
    ]

    result = ImportResult(
        mode=mode,
        total_rows=total_rows,
        valid_rows=valid_rows,
        created=created,
        updated=updated,
        skipped=skipped,
        errors=errors,
        rows=preview_rows,
    )

    if mode == "commit":
        if errors:
            return JSONResponse(status_code=422, content=result.model_dump())

        try:
            for r in processed_rows:
                if r["action"] == "create":
                    new_sched = ClassSchedule(
                        class_id=r["class_id"],
                        title=r["title"],
                        start_at=r["start_utc"],
                        end_at=r["end_utc"],
                        room=r["room"],
                        note=r["note"],
                    )
                    db.add(new_sched)
                elif r["action"] == "update":
                    sched = r["existing_schedule"]
                    if sched:
                        sched.title = r["title"]
                        sched.end_at = r["end_utc"]
                        sched.room = r["room"]
                        sched.note = r["note"]

            log_action(
                db,
                username,
                "schedules.import",
                detail={
                    "filename": filename,
                    "created": created,
                    "updated": updated,
                    "skipped": skipped,
                },
                ip_address=client_ip(request),
                commit=False,
            )
            db.commit()
        except Exception:
            db.rollback()
            raise

    return result
