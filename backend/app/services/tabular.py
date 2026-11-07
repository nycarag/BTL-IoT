"""Tabular data processing module (safe CSV and XLSX reader/writer)."""

from __future__ import annotations

import csv
import datetime
import io
import re
import zipfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

import defusedxml  # noqa: F401
import openpyxl
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from app.core.domain import remove_accents


class TabularError(ValueError):
    """Raised when tabular data is invalid, unreadable, or exceeds limits."""

    pass


_DANGEROUS_PREFIXES = ("=", "+", "-", "@")


def escape_cell(value: object) -> object:
    """Escape cell value to mitigate formula injection attacks."""
    if not isinstance(value, str):
        return value
    if value.startswith(("\t", "\r")) or value.lstrip().startswith(_DANGEROUS_PREFIXES):
        return "'" + value
    return value


def normalize_header(name: str) -> str:
    """Normalize header string: remove accents, lowercase, strip, replace space/dot/dash with underscore."""
    if not name:
        return ""
    text = remove_accents(name).strip().lower()
    text = re.sub(r"[\s.\-]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def _format_cell_value(val: object) -> str:
    """Format an Excel cell value into a string."""
    if val is None:
        return ""
    if isinstance(val, datetime.datetime):
        if val.hour == 0 and val.minute == 0 and val.second == 0 and val.microsecond == 0:
            return val.strftime("%d/%m/%Y")
        return val.strftime("%d/%m/%Y %H:%M")
    if isinstance(val, datetime.date):
        return val.strftime("%d/%m/%Y")
    if isinstance(val, datetime.time):
        return val.strftime("%H:%M")
    if isinstance(val, float):
        if val.is_integer():
            return str(int(val))
        return str(val)
    return str(val).strip()


def _iter_csv_rows(text: str) -> Generator[tuple[int, list[str]], None, None]:
    """Iterate lines from CSV text with automatic delimiter detection."""
    sample = text[:4096]
    delimiter = ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        delimiter = dialect.delimiter
    except Exception:
        delimiter = ","

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    for raw_row in reader:
        yield reader.line_num, [cell.strip() for cell in raw_row]


def _iter_xlsx_rows(data: bytes) -> Generator[tuple[int, list[str]], None, None]:
    """Iterate lines from XLSX bytes."""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (zipfile.BadZipFile, KeyError, Exception) as e:
        raise TabularError("Tệp Excel hỏng hoặc không đúng định dạng .xlsx") from e

    try:
        if not wb.worksheets:
            raise TabularError("Tệp Excel hỏng hoặc không đúng định dạng .xlsx")
        ws = wb.worksheets[0]
        for idx, raw_row in enumerate(ws.iter_rows(), start=1):
            real_row = next((c.row for c in raw_row if hasattr(c, "row") and c.row is not None), idx)
            cells = [_format_cell_value(c.value) for c in raw_row]
            yield real_row, cells
    except (zipfile.BadZipFile, KeyError, Exception) as e:
        if isinstance(e, TabularError):
            raise
        raise TabularError("Tệp Excel hỏng hoặc không đúng định dạng .xlsx") from e
    finally:
        wb.close()


def read_table(
    filename: str,
    data: bytes,
    *,
    max_bytes: int = 2 * 1024 * 1024,
    max_rows: int = 2000,
    max_cols: int = 30,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Safely read tabular data from CSV or XLSX bytes."""
    if len(data) > max_bytes:
        mb = max_bytes / (1024 * 1024)
        mb_str = f"{int(mb)}" if mb.is_integer() else f"{mb:.1f}"
        raise TabularError(f"Tệp vượt quá {mb_str} MiB")

    ext = Path(filename).suffix.lower()
    if ext not in (".csv", ".xlsx"):
        raise TabularError(f"Định dạng tệp '{ext}' không được hỗ trợ, chỉ chấp nhận .csv hoặc .xlsx")

    if ext == ".csv":
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = data.decode("cp1258")
            except UnicodeDecodeError:
                raise TabularError("Không đọc được bảng mã, hãy lưu tệp dạng CSV UTF-8")
        row_gen = _iter_csv_rows(text)
    else:
        row_gen = _iter_xlsx_rows(data)

    headers: list[str] = []
    valid_cols: list[tuple[int, str]] = []  # (col_index, normalized_header)
    rows: list[dict[str, Any]] = []
    header_found = False

    for real_row, cells in row_gen:
        # Bỏ qua dòng mà mọi ô rỗng
        if not any(cells):
            continue

        if not header_found:
            while cells and cells[-1] == "":
                cells.pop()

            if len(cells) > max_cols:
                raise TabularError(f"Số cột ({len(cells)}) vượt quá giới hạn ({max_cols})")

            seen_headers: set[str] = set()
            for col_idx, cell in enumerate(cells):
                norm = normalize_header(cell)
                if not norm:
                    # Cột tiêu đề rỗng bị bỏ
                    continue
                if norm in seen_headers:
                    raise TabularError(f"Cột '{norm}' bị trùng")
                seen_headers.add(norm)
                valid_cols.append((col_idx, norm))
                headers.append(norm)

            if not headers:
                raise TabularError("Tệp không có tiêu đề hợp lệ")

            if len(headers) > max_cols:
                raise TabularError(f"Số cột ({len(headers)}) vượt quá giới hạn ({max_cols})")

            header_found = True
            continue

        # Dòng dữ liệu
        while cells and cells[-1] == "":
            cells.pop()

        if len(cells) > max_cols:
            raise TabularError(f"Số cột ({len(cells)}) vượt quá giới hạn ({max_cols})")

        row_dict: dict[str, Any] = {}
        has_content = False
        for col_idx, norm in valid_cols:
            val = cells[col_idx] if col_idx < len(cells) else ""
            if val:
                has_content = True
            row_dict[norm] = val

        if not has_content:
            # Bỏ qua dòng mà mọi ô rỗng
            continue

        if len(rows) >= max_rows:
            raise TabularError(f"Số dòng dữ liệu vượt quá giới hạn ({max_rows})")

        row_dict["__row__"] = real_row
        rows.append(row_dict)

    if not rows:
        raise TabularError("Tệp không có dữ liệu")

    return headers, rows


def write_csv(headers: list[str], rows: list[list[object]]) -> bytes:
    """Write table to CSV bytes with UTF-8-SIG encoding and formula escaping."""
    output = io.StringIO()
    writer = csv.writer(output, delimiter=",")
    writer.writerow([escape_cell(h) if h is not None else "" for h in headers])
    for row in rows:
        formatted = []
        for cell in row:
            if cell is None:
                formatted.append("")
            elif isinstance(cell, str):
                formatted.append(escape_cell(cell))
            else:
                formatted.append(cell)
        writer.writerow(formatted)
    return output.getvalue().encode("utf-8-sig")


def write_xlsx(headers: list[str], rows: list[list[object]], sheet_name: str = "Sheet1") -> bytes:
    """Write table to XLSX bytes with styling and formula escaping."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name[:31] if sheet_name else "Sheet1"
    ws.freeze_panes = "A2"

    bold_font = Font(bold=True)

    escaped_headers = [escape_cell(h) if isinstance(h, str) else (h if h is not None else "") for h in headers]
    ws.append(escaped_headers)
    for cell in ws[1]:
        cell.font = bold_font

    for row in rows:
        formatted_row = [escape_cell(c) if isinstance(c, str) else c for c in row]
        ws.append(formatted_row)

    # Tính độ rộng cột = min(50, max(10, độ dài lớn nhất + 2))
    for col_idx in range(len(headers)):
        col_letter = get_column_letter(col_idx + 1)
        h_val = headers[col_idx]
        h_len = len(str(h_val)) if h_val is not None else 0
        r_lens = [len(str(r[col_idx])) for r in rows if col_idx < len(r) and r[col_idx] is not None]
        max_len = max([h_len] + r_lens) if ([h_len] + r_lens) else 0
        ws.column_dimensions[col_letter].width = min(50, max(10, max_len + 2))

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
