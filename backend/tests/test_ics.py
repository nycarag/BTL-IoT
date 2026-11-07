"""Tests for iCalendar (RFC 5545) build and parse service."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest

from app.services.ics import (
    ALLOWED_TZIDS,
    IcsError,
    VN_TZ,
    build_calendar,
    escape_text,
    fold_line,
    parse_calendar,
    unescape_text,
)


def test_escape_and_unescape_special_characters():
    """Title chứa dấu phẩy, chấm phẩy, xuống dòng và backslash được escape/unescape đúng."""
    raw = "Phòng Lab; IoT, AI \\ ML\nDòng 2: Thực hành; kiểm tra, OK"
    escaped = escape_text(raw)
    assert r"\;" in escaped
    assert r"\," in escaped
    assert r"\\" in escaped
    assert r"\n" in escaped
    assert "\n" not in escaped

    unescaped = unescape_text(escaped)
    assert unescaped == raw


def test_fold_line_rfc5545():
    """Kiểm tra gập dòng RFC 5545: mỗi dòng <= 75 byte UTF-8, dòng nối bắt đầu bằng space."""
    long_title = "SUMMARY:Lập trình mạng và hệ thống phân tán nâng cao cho sinh viên ngành Công nghệ thông tin học viện công nghệ bưu chính viễn thông Hà Nội"
    folded = fold_line(long_title)
    lines = folded.split("\r\n")
    assert len(lines) > 1

    for i, line in enumerate(lines):
        line_bytes = line.encode("utf-8")
        assert len(line_bytes) <= 75, f"Line {i} exceeds 75 octets: {len(line_bytes)}"
        if i > 0:
            assert line.startswith(" "), f"Continuation line {i} must start with space"

    # Khi bỏ gập dòng phải ra lại đúng xâu ban đầu
    unfolded = folded.replace("\r\n ", "")
    assert unfolded == long_title


def test_build_calendar_structure_and_limits():
    """Mọi dòng trong output <= 75 byte; output chứa CRLF; có BEGIN:VTIMEZONE."""
    events = [
        {
            "uid": "event-uuid-001",
            "title": "Lập trình mạng và hệ thống phân tán nâng cao cho sinh viên ngành Công nghệ thông tin - Khóa 2023 - Nhóm thực hành 02",
            "start_at": datetime(2026, 11, 10, 7, 0, tzinfo=VN_TZ),
            "end_at": datetime(2026, 11, 10, 9, 30, tzinfo=VN_TZ),
            "location": "Phòng 402-A2, Giảng đường A2, Học viện Công nghệ Bưu chính Viễn thông",
            "description": "Giảng viên hướng dẫn: TS. Nguyễn Văn A\nYêu cầu: Mang theo kit ESP32-CAM và tài liệu thực hành môn học.",
        }
    ]

    cal_bytes = build_calendar(events, calendar_name="Lịch học kỳ 1 2026-2027")
    assert isinstance(cal_bytes, bytes)
    assert b"\r\n" in cal_bytes
    assert b"BEGIN:VCALENDAR" in cal_bytes
    assert b"VERSION:2.0" in cal_bytes
    assert b"BEGIN:VTIMEZONE" in cal_bytes
    assert b"TZID:Asia/Ho_Chi_Minh" in cal_bytes
    assert b"TZOFFSETFROM:+0700" in cal_bytes
    assert b"TZOFFSETTO:+0700" in cal_bytes
    assert b"TZNAME:ICT" in cal_bytes
    assert b"DTSTART;TZID=Asia/Ho_Chi_Minh:20261110T070000" in cal_bytes
    assert b"DTEND;TZID=Asia/Ho_Chi_Minh:20261110T093000" in cal_bytes
    assert b"END:VCALENDAR\r\n" in cal_bytes

    # Kiểm tra mọi dòng không quá 75 octet UTF-8
    lines = cal_bytes.split(b"\r\n")
    # Dòng cuối sau \r\n kết thúc tệp là rỗng
    for i, line in enumerate(lines[:-1]):
        assert len(line) <= 75, f"Line {i} exceeds 75 octets: {len(line)} byte"


def test_round_trip_vietnamese_120_chars():
    """Round-trip: build rồi parse lại ra đúng title/giờ, kể cả title tiếng Việt dài 120 ký tự (bị gập dòng)."""
    # 120 ký tự tiếng Việt có dấu
    title_120 = (
        "Lập trình ứng dụng IoT và an toàn thông tin mạng nâng cao cơ sở đào tạo Hà Đông PTIT năm hai nghìn không trăm hai mươi sáu."
    )
    assert len(title_120) >= 120

    events = [
        {
            "uid": "sched-123@btl-iot.local",
            "title": title_120,
            "start_at": datetime(2026, 11, 6, 7, 0, tzinfo=VN_TZ),
            "end_at": datetime(2026, 11, 6, 9, 0, tzinfo=VN_TZ),
            "location": "Phòng 402-A2",
            "description": "Ghi chú buổi học số 1",
        }
    ]

    ics_data = build_calendar(events)
    parsed = parse_calendar(ics_data)

    assert len(parsed) == 1
    ev = parsed[0]
    assert ev["title"] == title_120
    assert ev["start_at"] == datetime(2026, 11, 6, 7, 0, tzinfo=VN_TZ)
    assert ev["end_at"] == datetime(2026, 11, 6, 9, 0, tzinfo=VN_TZ)
    assert ev["location"] == "Phòng 402-A2"
    assert ev["description"] == "Ghi chú buổi học số 1"
    assert ev["row"] == 1


def test_round_trip_multiple_events_and_escaping():
    """Kiểm tra xuất và nhập nhiều sự kiện với các ký tự đặc biệt."""
    events = [
        {
            "uid": "ev-1",
            "title": "Môn học: Lập trình C++; Dành cho CNTT, ATTT",
            "start_at": datetime(2026, 11, 8, 8, 0, tzinfo=VN_TZ),
            "end_at": datetime(2026, 11, 8, 10, 0, tzinfo=VN_TZ),
            "location": "Hội trường A2; Tầng 1",
            "description": "Chi tiết:\n- Đọc chương 1, 2;\n- Làm bài tập \\ mẫu.",
        },
        {
            "uid": "ev-2",
            "title": "Thực hành IoT",
            "start_at": datetime(2026, 11, 8, 13, 30, tzinfo=VN_TZ),
            "end_at": datetime(2026, 11, 8, 16, 30, tzinfo=VN_TZ),
            "location": None,
            "description": None,
        },
    ]

    ics_bytes = build_calendar(events)
    parsed = parse_calendar(ics_bytes)

    assert len(parsed) == 2
    assert parsed[0]["title"] == events[0]["title"]
    assert parsed[0]["location"] == events[0]["location"]
    assert parsed[0]["description"] == events[0]["description"]
    assert parsed[0]["row"] == 1

    assert parsed[1]["title"] == "Thực hành IoT"
    assert parsed[1]["location"] is None
    assert parsed[1]["description"] is None
    assert parsed[1]["row"] == 2


def test_parse_utc_z_to_vietnam_time():
    """Parse sự kiện dạng UTC 'Z' ra đúng giờ Việt Nam (+7)."""
    ics_text = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Test//EN\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:utc-event-1\r\n"
        "DTSTART:20261106T000000Z\r\n"
        "DTEND:20261106T020000Z\r\n"
        "SUMMARY:Buổi học sáng\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    parsed = parse_calendar(ics_text.encode("utf-8"))
    assert len(parsed) == 1
    # 00:00 UTC = 07:00 VN (+7)
    assert parsed[0]["start_at"] == datetime(2026, 11, 6, 7, 0, tzinfo=VN_TZ)
    # 02:00 UTC = 09:00 VN (+7)
    assert parsed[0]["end_at"] == datetime(2026, 11, 6, 9, 0, tzinfo=VN_TZ)


def test_parse_duration_when_dtend_missing():
    """Thiếu DTEND nhưng có DURATION dạng PT#H#M thì tính end_at = start_at + duration."""
    ics_text = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Test//EN\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:duration-event-1\r\n"
        "DTSTART;TZID=Asia/Ho_Chi_Minh:20261106T070000\r\n"
        "DURATION:PT2H30M\r\n"
        "SUMMARY:Học 2 tiếng rưỡi\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    parsed = parse_calendar(ics_text.encode("utf-8"))
    assert len(parsed) == 1
    assert parsed[0]["start_at"] == datetime(2026, 11, 6, 7, 0, tzinfo=VN_TZ)
    assert parsed[0]["end_at"] == datetime(2026, 11, 6, 9, 30, tzinfo=VN_TZ)


def test_parse_duration_hours_only():
    """DURATION dạng PT2H tính đúng 2 giờ."""
    ics_text = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Test//EN\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:duration-event-2\r\n"
        "DTSTART:20261106T070000\r\n"
        "DURATION:PT2H\r\n"
        "SUMMARY:Học 2 tiếng\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    parsed = parse_calendar(ics_text.encode("utf-8"))
    assert parsed[0]["end_at"] == datetime(2026, 11, 6, 9, 0, tzinfo=VN_TZ)


def test_error_missing_both_dtend_and_duration():
    """Thiếu cả DTEND và DURATION -> báo lỗi IcsError."""
    ics_text = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Test//EN\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:no-end\r\n"
        "DTSTART:20261106T070000\r\n"
        "SUMMARY:Không có giờ kết thúc\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    with pytest.raises(IcsError, match=r"Sự kiện thứ 1.*thiếu cả DTEND và DURATION"):
        parse_calendar(ics_text.encode("utf-8"))


def test_error_rrule():
    """VEVENT có RRULE -> báo IcsError có thông báo yêu cầu dạng từng buổi."""
    ics_text = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Test//EN\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:repeat-1\r\n"
        "DTSTART;TZID=Asia/Ho_Chi_Minh:20261106T070000\r\n"
        "DTEND;TZID=Asia/Ho_Chi_Minh:20261106T090000\r\n"
        "RRULE:FREQ=WEEKLY;COUNT=10\r\n"
        "SUMMARY:Lịch lặp hàng tuần\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    with pytest.raises(
        IcsError,
        match=r"Sự kiện thứ 1 lặp lại \(RRULE\) chưa được hỗ trợ, hãy xuất lịch dạng từng buổi",
    ):
        parse_calendar(ics_text.encode("utf-8"))


def test_error_all_day_value_date():
    """Sự kiện cả ngày (VALUE=DATE) -> báo IcsError."""
    ics_text = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Test//EN\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:all-day-1\r\n"
        "DTSTART;VALUE=DATE:20261106\r\n"
        "DTEND;VALUE=DATE:20261107\r\n"
        "SUMMARY:Nghỉ lễ cả ngày\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    with pytest.raises(IcsError, match=r"sự kiện cả ngày.*không phải buổi học"):
        parse_calendar(ics_text.encode("utf-8"))


def test_error_date_only_format():
    """DTSTART chỉ có 8 chữ số ngày YYYYMMDD -> coi là cả ngày -> IcsError."""
    ics_text = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Test//EN\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:all-day-2\r\n"
        "DTSTART:20261106\r\n"
        "DTEND:20261107\r\n"
        "SUMMARY:Hội thao\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    with pytest.raises(IcsError, match=r"sự kiện cả ngày.*không phải buổi học"):
        parse_calendar(ics_text.encode("utf-8"))


def test_error_unsupported_timezone():
    """Múi giờ khác Asia/Ho_Chi_Minh/Asia/Bangkok/Asia/Saigon -> IcsError kèm số thứ tự."""
    ics_text = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Test//EN\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:ny-tz\r\n"
        "DTSTART;TZID=America/New_York:20261106T070000\r\n"
        "DTEND;TZID=America/New_York:20261106T090000\r\n"
        "SUMMARY:Giờ Mỹ\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    with pytest.raises(IcsError, match=r"Sự kiện thứ 1: múi giờ 'America/New_York' chưa được hỗ trợ"):
        parse_calendar(ics_text.encode("utf-8"))


def test_allowed_timezones_bangkok_and_saigon():
    """Asia/Bangkok và Asia/Saigon là múi giờ hợp lệ (+07:00)."""
    ics_text = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Test//EN\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:bkk\r\n"
        "DTSTART;TZID=Asia/Bangkok:20261106T070000\r\n"
        "DTEND;TZID=Asia/Saigon:20261106T090000\r\n"
        "SUMMARY:Giờ BKK và Saigon\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    parsed = parse_calendar(ics_text.encode("utf-8"))
    assert len(parsed) == 1
    assert parsed[0]["start_at"] == datetime(2026, 11, 6, 7, 0, tzinfo=VN_TZ)
    assert parsed[0]["end_at"] == datetime(2026, 11, 6, 9, 0, tzinfo=VN_TZ)


def test_error_garbage_bytes():
    """Dữ liệu bytes rác (không phải UTF-8) -> báo IcsError."""
    garbage = b"\x80\x81\xff\xfe\x00\x01\x02\x03"
    with pytest.raises(IcsError, match=r"Dữ liệu iCalendar không phải UTF-8 hợp lệ"):
        parse_calendar(garbage)


def test_error_non_vcalendar():
    """Dữ liệu không phải VCALENDAR -> báo IcsError."""
    plain_text = b"This is just a regular text file, not a VCALENDAR file."
    with pytest.raises(IcsError, match=r"không phải định dạng VCALENDAR"):
        parse_calendar(plain_text)


def test_error_max_bytes_exceeded():
    """Dung lượng vượt quá max_bytes -> báo IcsError."""
    data = b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"
    with pytest.raises(IcsError, match=r"Dung lượng tệp vượt quá giới hạn"):
        parse_calendar(data, max_bytes=10)


def test_error_max_events_exceeded():
    """Số lượng sự kiện vượt quá max_events -> báo IcsError."""
    ics_text = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:1\r\n"
        "DTSTART:20261106T070000\r\n"
        "DTEND:20261106T090000\r\n"
        "SUMMARY:Buổi 1\r\n"
        "END:VEVENT\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:2\r\n"
        "DTSTART:20261106T100000\r\n"
        "DTEND:20261106T120000\r\n"
        "SUMMARY:Buổi 2\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    with pytest.raises(IcsError, match=r"Số lượng sự kiện vượt quá giới hạn"):
        parse_calendar(ics_text.encode("utf-8"), max_events=1)


def test_unfolding_with_tab_and_lf():
    """Chấp nhận gập dòng bằng tab và xuống dòng đơn \\n."""
    ics_text = (
        "BEGIN:VCALENDAR\n"
        "VERSION:2.0\n"
        "BEGIN:VEVENT\n"
        "UID:unfold-test\n"
        "DTSTART:20261106T070000\n"
        "DTEND:20261106T090000\n"
        "SUMMARY:Lập trình\n"
        "\tmạng và\n"
        " hệ thống\n"
        "END:VEVENT\n"
        "END:VCALENDAR\n"
    )
    parsed = parse_calendar(ics_text.encode("utf-8"))
    assert len(parsed) == 1
    assert parsed[0]["title"] == "Lập trìnhmạng vàhệ thống"


def test_naive_datetime_handling_in_build():
    """Nếu sự kiện truyền vào datetime naive thì tự động coi là UTC per rule 6."""
    events = [
        {
            "uid": "naive-dt",
            "title": "Naive Datetime Event",
            "start_at": datetime(2026, 11, 6, 0, 0),  # 00:00 naive (coi là UTC) -> 07:00 VN
            "end_at": datetime(2026, 11, 6, 2, 0),    # 02:00 naive (coi là UTC) -> 09:00 VN
        }
    ]
    ics_bytes = build_calendar(events)
    parsed = parse_calendar(ics_bytes)
    assert parsed[0]["start_at"] == datetime(2026, 11, 6, 7, 0, tzinfo=VN_TZ)
    assert parsed[0]["end_at"] == datetime(2026, 11, 6, 9, 0, tzinfo=VN_TZ)
