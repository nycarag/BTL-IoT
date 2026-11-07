"""Router for importing and exporting student rosters."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import verify_token
from app.database import get_db
from app.models.school import AuditLog, ClassRoom, FaceReference, Student
from app.schemas.roster_io import ImportError as RosterImportError, ImportResult
from app.services.audit import client_ip, log_action
from app.services.tabular import (
    TabularError,
    normalize_header,
    read_table,
    write_csv,
    write_xlsx,
)

router = APIRouter()

VN_TZ = timezone(timedelta(hours=7), "ICT")
MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MiB

COL_MAP = {
    "student_code": {"ma_sv", "mssv", "ma_sinh_vien", "student_code", "id"},
    "name": {"ho_va_ten", "ho_ten", "ten", "name", "full_name"},
    "date_of_birth": {"ngay_sinh", "dob", "date_of_birth"},
    "class_code": {"ma_lop", "lop", "class", "class_code"},
}


def _parse_date_of_birth(val: object, row: int) -> tuple[str | None, RosterImportError | None]:
    """Parse and validate date of birth string.

    Accepts dd/mm/yyyy, d/m/yyyy, yyyy-mm-dd, dd-mm-yyyy.
    Standardizes output to dd/mm/yyyy.
    Returns (normalized_dob, error_or_none).
    """
    if val is None:
        return None, None
    s = str(val).strip()
    if not s:
        return None, None

    m_dmy = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$", s)
    m_ymd = re.match(r"^(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})$", s)

    if m_dmy:
        d, m, y = int(m_dmy.group(1)), int(m_dmy.group(2)), int(m_dmy.group(3))
    elif m_ymd:
        y, m, d = int(m_ymd.group(1)), int(m_ymd.group(2)), int(m_ymd.group(3))
    else:
        return None, RosterImportError(
            row=row,
            field="date_of_birth",
            message=f"Ngày sinh '{s}' không đúng định dạng (chấp nhận dd/mm/yyyy hoặc yyyy-mm-dd)",
        )

    try:
        datetime(y, m, d)
    except ValueError:
        return None, RosterImportError(
            row=row,
            field="date_of_birth",
            message=f"Ngày sinh '{s}' không có thật",
        )

    current_year = datetime.now().year
    if not (1950 <= y <= current_year):
        return None, RosterImportError(
            row=row,
            field="date_of_birth",
            message=f"Năm sinh phải từ 1950 đến {current_year}",
        )

    return f"{d:02d}/{m:02d}/{y:04d}", None


def _parse_rows(
    raw_items: list[dict[str, Any]],
    mode: str,
    on_conflict: str,
    create_missing_classes: bool,
    db: Session,
) -> tuple[ImportResult, list[dict[str, Any]], set[str], dict[str, int], dict[str, Student]]:
    """Validate each raw item, check conflicts with DB and track actions."""
    existing_classes = {c.code: c.id for c in db.scalars(select(ClassRoom))}
    existing_students = {s.student_code: s for s in db.scalars(select(Student))}

    seen_codes: dict[str, int] = {}
    to_create_classes: set[str] = set()
    errors: list[RosterImportError] = []
    processed_rows: list[dict[str, Any]] = []
    valid_rows_data: list[dict[str, Any]] = []

    created = 0
    updated = 0
    skipped = 0

    for item in raw_items:
        row_num = item["row"]
        row_errors: list[RosterImportError] = []

        if item.get("__invalid__"):
            row_errors.append(
                RosterImportError(row=row_num, field=None, message="Dòng không phải là đối tượng hợp lệ")
            )

        # 1. student_code
        val_code = item.get("student_code")
        code_raw = str(val_code or "").strip()
        if not code_raw:
            row_errors.append(
                RosterImportError(row=row_num, field="student_code", message="Mã sinh viên không được để trống")
            )
            code = ""
        else:
            code = code_raw.upper()
            if not re.match(r"^[A-Z0-9_-]{1,32}$", code):
                row_errors.append(
                    RosterImportError(
                        row=row_num,
                        field="student_code",
                        message="Mã sinh viên không hợp lệ (chỉ gồm chữ hoa, số, gạch dưới, gạch ngang, từ 1-32 ký tự)",
                    )
                )
            elif code in seen_codes:
                first_row = seen_codes[code]
                row_errors.append(
                    RosterImportError(
                        row=row_num,
                        field="student_code",
                        message=f"Mã SV trùng với dòng {first_row}",
                    )
                )
            else:
                seen_codes[code] = row_num

        # 2. name
        val_name = item.get("name")
        name_raw = str(val_name or "")
        name = " ".join(name_raw.split())
        if not name:
            row_errors.append(
                RosterImportError(row=row_num, field="name", message="Họ và tên không được để trống")
            )
        elif len(name) > 255:
            row_errors.append(
                RosterImportError(row=row_num, field="name", message="Họ và tên không được vượt quá 255 ký tự")
            )

        # 3. date_of_birth
        val_dob = item.get("date_of_birth")
        dob_normalized, dob_err = _parse_date_of_birth(val_dob, row_num)
        if dob_err:
            row_errors.append(dob_err)

        # 4. class_code
        val_class = item.get("class_code")
        class_code = str(val_class or "").strip() if val_class is not None else ""
        class_code = class_code if class_code else None

        if class_code:
            if class_code in existing_classes or class_code in to_create_classes:
                pass
            elif create_missing_classes:
                to_create_classes.add(class_code)
            else:
                row_errors.append(
                    RosterImportError(
                        row=row_num,
                        field="class_code",
                        message=f"Lớp '{class_code}' không tồn tại",
                    )
                )

        if row_errors:
            action = "error"
            errors.extend(row_errors)
        else:
            if code in existing_students:
                if on_conflict == "skip":
                    action = "skip"
                    skipped += 1
                else:
                    action = "update"
                    updated += 1
            else:
                action = "create"
                created += 1

            valid_rows_data.append({
                "row": row_num,
                "student_code": code,
                "name": name,
                "date_of_birth": dob_normalized,
                "class_code": class_code,
                "action": action,
            })

        processed_rows.append({
            "row": row_num,
            "student_code": code,
            "name": name,
            "date_of_birth": dob_normalized if not any(e.field == "date_of_birth" for e in row_errors) else (str(val_dob) if val_dob else None),
            "class_code": class_code,
            "action": action,
        })

    result = ImportResult(
        mode=mode,
        total_rows=len(raw_items),
        valid_rows=len(valid_rows_data),
        created=created,
        updated=updated,
        skipped=skipped,
        errors=errors,
        rows=processed_rows[:50],
    )
    return result, valid_rows_data, to_create_classes, existing_classes, existing_students


def _apply_rows(
    db: Session,
    valid_rows: list[dict[str, Any]],
    to_create_classes: set[str],
    existing_classes: dict[str, int],
    existing_students: dict[str, Student],
    username: str,
    filename: str,
    created: int,
    updated: int,
    skipped: int,
    request: Request | None,
) -> None:
    """Commit validated roster rows into database in a single transaction."""
    # 1. Tạo các lớp còn thiếu nếu được bật
    for c_code in sorted(to_create_classes):
        if c_code not in existing_classes:
            new_cls = ClassRoom(code=c_code, name=c_code)
            db.add(new_cls)
            db.flush()
            existing_classes[c_code] = new_cls.id

    # 2. Thêm hoặc cập nhật sinh viên
    for r in valid_rows:
        action = r["action"]
        code = r["student_code"]
        class_code = r["class_code"]
        class_id = existing_classes.get(class_code) if class_code else None

        if action == "create":
            st = Student(
                student_code=code,
                name=r["name"],
                date_of_birth=r["date_of_birth"],
                class_id=class_id,
            )
            db.add(st)
            existing_students[code] = st
        elif action == "update":
            st = existing_students[code]
            st.name = r["name"]
            st.date_of_birth = r["date_of_birth"]
            st.class_id = class_id
            # KHÔNG đụng FaceReference, KHÔNG đụng Attendance
        elif action == "skip":
            pass

    # 3. Ghi audit log cùng transaction
    log_action(
        db,
        actor=username,
        action="students.import",
        target=None,
        detail={
            "filename": filename,
            "created": created,
            "updated": updated,
            "skipped": skipped,
        },
        ip_address=client_ip(request) if request else None,
        commit=False,
    )

    # 4. Commit transaction
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, "Lỗi khi ghi dữ liệu sinh viên vào cơ sở dữ liệu") from exc


@router.get("/students/export")
def export_students(
    request: Request,
    format: str = "csv",
    class_id: int | None = None,
    username: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Xuất danh sách sinh viên dưới dạng CSV hoặc XLSX."""
    fmt = format.lower().strip()
    if fmt not in ("csv", "xlsx"):
        raise HTTPException(422, "Định dạng không được hỗ trợ (chỉ nhận csv hoặc xlsx)")

    class_code_str = "tat_ca"
    if class_id is not None:
        class_room = db.get(ClassRoom, class_id)
        if not class_room:
            raise HTTPException(404, "Không tìm thấy lớp")
        class_code_str = class_room.code

    stmt = (
        select(
            Student,
            ClassRoom.code,
            FaceReference.student_id.is_not(None),
        )
        .outerjoin(ClassRoom, Student.class_id == ClassRoom.id)
        .outerjoin(FaceReference, Student.id == FaceReference.student_id)
        .order_by(Student.student_code.asc())
    )
    if class_id is not None:
        stmt = stmt.where(Student.class_id == class_id)

    db_results = db.execute(stmt).all()

    headers = ["STT", "Mã SV", "Họ và tên", "Ngày sinh", "Mã lớp", "Đã đăng ký khuôn mặt"]
    rows: list[list[object]] = []
    for idx, (st, class_code, enrolled) in enumerate(db_results, start=1):
        rows.append([
            idx,
            st.student_code,
            st.name,
            st.date_of_birth or "",
            class_code or "",
            "Có" if enrolled else "Không",
        ])

    now_vn = datetime.now(VN_TZ).strftime("%Y%m%d")
    filename = f"sinh_vien_{class_code_str}_{now_vn}.{fmt}"

    if fmt == "csv":
        content = write_csv(headers, rows)
        media_type = "text/csv; charset=utf-8"
    else:
        content = write_xlsx(headers, rows, sheet_name="SinhVien")
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    log_action(
        db,
        actor=username,
        action="students.export",
        target=None,
        detail={"format": fmt, "class_id": class_id, "count": len(rows)},
        ip_address=client_ip(request),
    )

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/students/import-template")
def get_import_template(
    format: str = "csv",
    _: str = Depends(verify_token),
):
    """Tải tệp mẫu nhập sinh viên."""
    fmt = format.lower().strip()
    if fmt not in ("csv", "xlsx"):
        raise HTTPException(422, "Định dạng không được hỗ trợ (chỉ nhận csv hoặc xlsx)")

    headers = ["STT", "Mã SV", "Họ và tên", "Ngày sinh", "Mã lớp"]
    rows: list[list[object]] = [
        [1, "B23DCAT999", "Nguyễn Văn Mẫu", "01/01/2005", "D23CTAT01-B"]
    ]
    filename = f"mau_nhap_sinh_vien.{fmt}"

    if fmt == "csv":
        content = write_csv(headers, rows)
        media_type = "text/csv; charset=utf-8"
    else:
        content = write_xlsx(headers, rows, sheet_name="MauNhap")
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/students/import", response_model=ImportResult)
async def import_students(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Form("preview"),
    on_conflict: str = Form("skip"),
    create_missing_classes: bool = Form(False),
    username: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Nhập danh sách sinh viên từ tệp CSV, XLSX hoặc JSON."""
    if mode not in ("preview", "commit"):
        raise HTTPException(422, "mode phải là 'preview' hoặc 'commit'")
    if on_conflict not in ("skip", "update"):
        raise HTTPException(422, "on_conflict phải là 'skip' hoặc 'update'")

    filename = file.filename or ""
    ext = Path(filename).suffix.lower()
    if ext not in (".csv", ".xlsx", ".json"):
        raise HTTPException(
            415,
            f"Định dạng tệp '{ext}' không được hỗ trợ, chỉ chấp nhận .csv, .xlsx hoặc .json",
        )

    # Đọc tối đa 2 MiB + 1 byte
    content = await file.read(MAX_FILE_BYTES + 2)
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(413, "Dung lượng tệp vượt quá 2 MiB")

    raw_items: list[dict[str, Any]] = []

    if ext in (".csv", ".xlsx"):
        try:
            headers, table_rows = read_table(filename, content, max_rows=2000)
        except TabularError as e:
            err_res = ImportResult(
                mode=mode,
                total_rows=0,
                valid_rows=0,
                created=0,
                updated=0,
                skipped=0,
                errors=[RosterImportError(row=1, field=None, message=str(e))],
                rows=[],
            )
            return JSONResponse(status_code=422, content=err_res.model_dump())

        student_code_col: str | None = None
        name_col: str | None = None
        dob_col: str | None = None
        class_col: str | None = None

        for h in headers:
            if not student_code_col and h in COL_MAP["student_code"]:
                student_code_col = h
            elif not name_col and h in COL_MAP["name"]:
                name_col = h
            elif not dob_col and h in COL_MAP["date_of_birth"]:
                dob_col = h
            elif not class_col and h in COL_MAP["class_code"]:
                class_col = h

        if not student_code_col or not name_col:
            missing_field = "student_code" if not student_code_col else "name"
            missing_label = "Mã sinh viên" if not student_code_col else "Họ và tên"
            err_res = ImportResult(
                mode=mode,
                total_rows=0,
                valid_rows=0,
                created=0,
                updated=0,
                skipped=0,
                errors=[
                    RosterImportError(
                        row=1,
                        field=missing_field,
                        message=f"Thiếu cột bắt buộc: {missing_label}",
                    )
                ],
                rows=[],
            )
            return JSONResponse(status_code=422, content=err_res.model_dump())

        for r in table_rows:
            raw_items.append({
                "row": r.get("__row__", len(raw_items) + 2),
                "student_code": r.get(student_code_col),
                "name": r.get(name_col),
                "date_of_birth": r.get(dob_col) if dob_col else None,
                "class_code": r.get(class_col) if class_col else None,
            })

    elif ext == ".json":
        try:
            json_data = json.loads(content.decode("utf-8-sig"))
        except Exception:
            err_res = ImportResult(
                mode=mode,
                total_rows=0,
                valid_rows=0,
                created=0,
                updated=0,
                skipped=0,
                errors=[RosterImportError(row=1, field=None, message="Tệp JSON hỏng hoặc không đúng định dạng")],
                rows=[],
            )
            return JSONResponse(status_code=422, content=err_res.model_dump())

        if not isinstance(json_data, list):
            err_res = ImportResult(
                mode=mode,
                total_rows=0,
                valid_rows=0,
                created=0,
                updated=0,
                skipped=0,
                errors=[RosterImportError(row=1, field=None, message="Tệp JSON phải là mảng các đối tượng sinh viên")],
                rows=[],
            )
            return JSONResponse(status_code=422, content=err_res.model_dump())

        if len(json_data) > 2000:
            err_res = ImportResult(
                mode=mode,
                total_rows=len(json_data),
                valid_rows=0,
                created=0,
                updated=0,
                skipped=0,
                errors=[RosterImportError(row=1, field=None, message="Số lượng phần tử trong tệp JSON vượt quá giới hạn 2000")],
                rows=[],
            )
            return JSONResponse(status_code=422, content=err_res.model_dump())

        if not json_data:
            err_res = ImportResult(
                mode=mode,
                total_rows=0,
                valid_rows=0,
                created=0,
                updated=0,
                skipped=0,
                errors=[RosterImportError(row=1, field=None, message="Tệp JSON không có dữ liệu")],
                rows=[],
            )
            return JSONResponse(status_code=422, content=err_res.model_dump())

        first_obj = next((x for x in json_data if isinstance(x, dict)), None)
        if not first_obj:
            err_res = ImportResult(
                mode=mode,
                total_rows=len(json_data),
                valid_rows=0,
                created=0,
                updated=0,
                skipped=0,
                errors=[RosterImportError(row=1, field=None, message="Tệp JSON không chứa đối tượng sinh viên hợp lệ")],
                rows=[],
            )
            return JSONResponse(status_code=422, content=err_res.model_dump())

        def _find_key(keys_in_obj: list[str], target_set: set[str]) -> str | None:
            for k in keys_in_obj:
                if normalize_header(k) in target_set:
                    return k
            return None

        j_student_code_key = _find_key(list(first_obj.keys()), COL_MAP["student_code"])
        j_name_key = _find_key(list(first_obj.keys()), COL_MAP["name"])
        j_dob_key = _find_key(list(first_obj.keys()), COL_MAP["date_of_birth"])
        j_class_key = _find_key(list(first_obj.keys()), COL_MAP["class_code"])

        if not j_student_code_key or not j_name_key:
            missing_field = "student_code" if not j_student_code_key else "name"
            missing_label = "Mã sinh viên" if not j_student_code_key else "Họ và tên"
            err_res = ImportResult(
                mode=mode,
                total_rows=0,
                valid_rows=0,
                created=0,
                updated=0,
                skipped=0,
                errors=[
                    RosterImportError(
                        row=1,
                        field=missing_field,
                        message=f"Thiếu cột bắt buộc: {missing_label}",
                    )
                ],
                rows=[],
            )
            return JSONResponse(status_code=422, content=err_res.model_dump())

        for idx, obj in enumerate(json_data):
            row_num = idx + 2
            if not isinstance(obj, dict):
                raw_items.append({
                    "row": row_num,
                    "student_code": None,
                    "name": None,
                    "date_of_birth": None,
                    "class_code": None,
                    "__invalid__": True,
                })
            else:
                raw_items.append({
                    "row": row_num,
                    "student_code": obj.get(j_student_code_key),
                    "name": obj.get(j_name_key),
                    "date_of_birth": obj.get(j_dob_key) if j_dob_key else None,
                    "class_code": obj.get(j_class_key) if j_class_key else None,
                })

    result, valid_rows_data, to_create_classes, existing_classes, existing_students = _parse_rows(
        raw_items, mode, on_conflict, create_missing_classes, db
    )

    if mode == "commit":
        if result.errors:
            return JSONResponse(status_code=422, content=result.model_dump())

        _apply_rows(
            db,
            valid_rows_data,
            to_create_classes,
            existing_classes,
            existing_students,
            username,
            filename,
            result.created,
            result.updated,
            result.skipped,
            request,
        )

    return result
