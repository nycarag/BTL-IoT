"""Module xuất và nhập lịch dạng iCalendar (RFC 5545)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
import uuid

# Múi giờ Việt Nam (+07:00 ICT) theo quy ước dự án
VN_TZ = timezone(timedelta(hours=7), "ICT")

# Các TZID hợp lệ được chấp nhận coi là giờ Việt Nam (+07:00)
ALLOWED_TZIDS = {"asia/ho_chi_minh", "asia/bangkok", "asia/saigon"}


class IcsError(ValueError):
    """Lỗi xử lý tệp iCalendar (.ics)."""
    pass


def escape_text(text: str | None) -> str:
    """Escape giá trị text theo RFC 5545 (3.3.11)."""
    if text is None:
        return ""
    text = str(text)
    # Thứ tự: backslash trước, rồi dấu chấm phẩy, phẩy, và ký tự xuống dòng
    text = text.replace("\\", "\\\\")
    text = text.replace(";", r"\;")
    text = text.replace(",", r"\,")
    text = text.replace("\r\n", r"\n").replace("\r", r"\n").replace("\n", r"\n")
    return text


def unescape_text(text: str) -> str:
    """Unescape giá trị text ngược lại theo RFC 5545."""
    if not text:
        return text

    def _replace(match: re.Match[str]) -> str:
        ch = match.group(1)
        if ch in ("n", "N"):
            return "\n"
        return ch

    return re.sub(r"\\([\\;,nN])", _replace, text)


def fold_line(line: str, max_octets: int = 75) -> str:
    """Gập dòng theo RFC 5545 (tối đa max_octets UTF-8 byte mỗi dòng).

    Dòng nối bắt đầu bằng 1 dấu cách (chiếm 1 octet).
    Không cắt giữa ký tự nhiều byte UTF-8.
    """
    line_bytes = line.encode("utf-8")
    if len(line_bytes) <= max_octets:
        return line

    chunks: list[str] = []
    current_chars: list[str] = []
    current_octets = 0
    limit = max_octets

    for char in line:
        char_octets = len(char.encode("utf-8"))
        if current_octets + char_octets > limit:
            chunks.append("".join(current_chars))
            current_chars = [char]
            current_octets = char_octets
            limit = max_octets - 1  # 1 byte dành cho dấu cách ở đầu dòng nối
        else:
            current_chars.append(char)
            current_octets += char_octets

    if current_chars:
        chunks.append("".join(current_chars))

    return "\r\n ".join(chunks)


def build_calendar(events: list[dict], *, calendar_name: str = "Lich hoc BTL-IoT") -> bytes:
    """Tạo nội dung file iCalendar (.ics) từ danh sách sự kiện."""
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//PTIT Nhom05//BTL-IoT Attendance//VI",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape_text(calendar_name)}",
        "X-WR-TIMEZONE:Asia/Ho_Chi_Minh",
        "BEGIN:VTIMEZONE",
        "TZID:Asia/Ho_Chi_Minh",
        "BEGIN:STANDARD",
        "DTSTART:19700101T000000",
        "TZOFFSETFROM:+0700",
        "TZOFFSETTO:+0700",
        "TZNAME:ICT",
        "END:STANDARD",
        "END:VTIMEZONE",
    ]

    now_utc_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    for ev in events:
        lines.append("BEGIN:VEVENT")
        uid = str(ev.get("uid") or uuid.uuid4())
        lines.append(f"UID:{escape_text(uid)}")

        # DTSTAMP (UTC, dạng 20261106T030000Z)
        if ev.get("dtstamp"):
            ds = ev["dtstamp"]
            if isinstance(ds, datetime):
                if ds.tzinfo is None:
                    ds = ds.replace(tzinfo=timezone.utc)
                lines.append(f"DTSTAMP:{ds.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}")
            else:
                lines.append(f"DTSTAMP:{ds}")
        else:
            lines.append(f"DTSTAMP:{now_utc_str}")

        # DTSTART (giờ VN)
        start_at = ev.get("start_at")
        if start_at is None:
            raise IcsError("Sự kiện thiếu start_at")
        if start_at.tzinfo is None:
            start_at = start_at.replace(tzinfo=timezone.utc)
        start_vn = start_at.astimezone(VN_TZ).strftime("%Y%m%dT%H%M%S")
        lines.append(f"DTSTART;TZID=Asia/Ho_Chi_Minh:{start_vn}")

        # DTEND (giờ VN)
        end_at = ev.get("end_at")
        if end_at is None:
            raise IcsError("Sự kiện thiếu end_at")
        if end_at.tzinfo is None:
            end_at = end_at.replace(tzinfo=timezone.utc)
        end_vn = end_at.astimezone(VN_TZ).strftime("%Y%m%dT%H%M%S")
        lines.append(f"DTEND;TZID=Asia/Ho_Chi_Minh:{end_vn}")

        # SUMMARY
        title = ev.get("title") or ""
        lines.append(f"SUMMARY:{escape_text(title)}")

        # LOCATION (nếu có)
        location = ev.get("location")
        if location:
            lines.append(f"LOCATION:{escape_text(str(location))}")

        # DESCRIPTION (nếu có)
        description = ev.get("description")
        if description:
            lines.append(f"DESCRIPTION:{escape_text(str(description))}")

        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")

    folded_lines = [fold_line(line) for line in lines]
    return ("\r\n".join(folded_lines) + "\r\n").encode("utf-8")


def _parse_datetime(name: str, val: str, params: dict[str, str], row: int) -> datetime:
    val = val.strip()
    if params.get("VALUE", "").upper() == "DATE" or (len(val) == 8 and val.isdigit()):
        raise IcsError(f"Sự kiện thứ {row}: sự kiện cả ngày (VALUE=DATE) không phải buổi học")

    tzid = params.get("TZID")
    if tzid:
        norm_tzid = tzid.strip().lstrip("/").lower()
        if norm_tzid not in ALLOWED_TZIDS:
            raise IcsError(f"Sự kiện thứ {row}: múi giờ '{tzid}' chưa được hỗ trợ")

    if val.endswith("Z") or val.endswith("z"):
        try:
            dt_utc = datetime.strptime(val.rstrip("zZ"), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            try:
                dt_utc = datetime.strptime(val.rstrip("zZ"), "%Y%m%dT%H%M").replace(tzinfo=timezone.utc)
            except ValueError as exc:
                raise IcsError(f"Sự kiện thứ {row}: định dạng thời gian '{val}' không hợp lệ") from exc
        return dt_utc.astimezone(VN_TZ)
    else:
        try:
            return datetime.strptime(val, "%Y%m%dT%H%M%S").replace(tzinfo=VN_TZ)
        except ValueError:
            try:
                return datetime.strptime(val, "%Y%m%dT%H%M").replace(tzinfo=VN_TZ)
            except ValueError as exc:
                raise IcsError(f"Sự kiện thứ {row}: định dạng thời gian '{val}' không hợp lệ") from exc


def _parse_duration(val: str, row: int) -> timedelta:
    val = val.strip()
    m = re.match(r"^\+?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$", val, re.IGNORECASE)
    if not m or val.upper() in ("P", "PT"):
        raise IcsError(f"Sự kiện thứ {row}: DURATION '{val}' không hợp lệ")
    weeks = int(m.group(1) or 0)
    days = int(m.group(2) or 0)
    hours = int(m.group(3) or 0)
    minutes = int(m.group(4) or 0)
    seconds = int(m.group(5) or 0)
    delta = timedelta(weeks=weeks, days=days, hours=hours, minutes=minutes, seconds=seconds)
    if delta.total_seconds() <= 0:
        raise IcsError(f"Sự kiện thứ {row}: DURATION phải lớn hơn 0")
    return delta


def _parse_vevent(lines: list[str], row: int) -> dict:
    summary: str | None = None
    dtstart: datetime | None = None
    dtend: datetime | None = None
    duration: timedelta | None = None
    location: str | None = None
    description: str | None = None
    has_rrule = False

    for line in lines:
        if ":" not in line:
            continue
        prop_spec, _, prop_val = line.partition(":")
        parts = prop_spec.split(";")
        name = parts[0].strip().upper()
        params: dict[str, str] = {}
        for p in parts[1:]:
            if "=" in p:
                k, _, v = p.partition("=")
                params[k.strip().upper()] = v.strip().strip('"')
            else:
                params[p.strip().upper()] = ""

        if name == "RRULE":
            has_rrule = True
        elif name == "SUMMARY":
            summary = unescape_text(prop_val)
        elif name == "DTSTART":
            dtstart = _parse_datetime(name, prop_val, params, row)
        elif name == "DTEND":
            dtend = _parse_datetime(name, prop_val, params, row)
        elif name == "DURATION":
            duration = _parse_duration(prop_val, row)
        elif name == "LOCATION":
            location = unescape_text(prop_val)
        elif name == "DESCRIPTION":
            description = unescape_text(prop_val)

    if has_rrule:
        raise IcsError(f"Sự kiện thứ {row} lặp lại (RRULE) chưa được hỗ trợ, hãy xuất lịch dạng từng buổi")

    if dtstart is None:
        raise IcsError(f"Sự kiện thứ {row} thiếu DTSTART")

    if dtend is not None:
        end_at = dtend
    elif duration is not None:
        end_at = dtstart + duration
    else:
        raise IcsError(f"Sự kiện thứ {row} thiếu cả DTEND và DURATION")

    if end_at < dtstart:
        raise IcsError(f"Sự kiện thứ {row}: thời gian kết thúc trước thời gian bắt đầu")

    return {
        "title": summary if summary is not None else "",
        "start_at": dtstart,
        "end_at": end_at,
        "location": location if location else None,
        "description": description if description else None,
        "row": row,
    }


def parse_calendar(data: bytes, *, max_bytes: int = 1024 * 1024, max_events: int = 1000) -> list[dict]:
    """Phân tích dữ liệu file iCalendar (.ics) thành danh sách sự kiện."""
    if not isinstance(data, (bytes, bytearray)):
        raise IcsError("Dữ liệu iCalendar phải là bytes")
    if len(data) > max_bytes:
        raise IcsError(f"Dung lượng tệp vượt quá giới hạn ({len(data)} > {max_bytes} bytes)")

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IcsError("Dữ liệu iCalendar không phải UTF-8 hợp lệ") from exc

    if text.startswith("\ufeff"):
        text = text[1:]

    # Chuẩn hóa xuống dòng và bỏ gập dòng (dòng bắt đầu bằng space/tab nối vào dòng trước)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    unfolded = re.sub(r"\n[ \t]", "", text)
    raw_lines = unfolded.split("\n")

    upper_lines = [l.strip().upper() for l in raw_lines if l.strip()]
    if "BEGIN:VCALENDAR" not in upper_lines or "END:VCALENDAR" not in upper_lines:
        raise IcsError("Dữ liệu không phải định dạng VCALENDAR hợp lệ")
    if upper_lines.index("BEGIN:VCALENDAR") >= upper_lines.index("END:VCALENDAR"):
        raise IcsError("Dữ liệu không phải định dạng VCALENDAR hợp lệ")

    events: list[dict] = []
    in_vevent = False
    current_lines: list[str] = []
    event_count = 0

    for line in raw_lines:
        sline = line.strip()
        if not sline:
            continue
        if sline.upper() == "BEGIN:VEVENT":
            in_vevent = True
            current_lines = []
            event_count += 1
            if event_count > max_events:
                raise IcsError(f"Số lượng sự kiện vượt quá giới hạn ({max_events})")
        elif sline.upper() == "END:VEVENT":
            if in_vevent:
                ev = _parse_vevent(current_lines, row=event_count)
                events.append(ev)
                in_vevent = False
        elif in_vevent:
            current_lines.append(sline)

    if in_vevent:
        raise IcsError("Tệp iCalendar kết thúc đột ngột trước khi đóng VEVENT")

    return events
