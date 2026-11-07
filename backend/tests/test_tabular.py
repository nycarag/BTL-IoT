"""Unit tests for services/tabular.py (CSV/XLSX safe processing)."""

from __future__ import annotations

import datetime
import io
import unittest

import openpyxl

from app.services.tabular import (
    TabularError,
    escape_cell,
    normalize_header,
    read_table,
    write_csv,
    write_xlsx,
)


class TestTabularService(unittest.TestCase):
    def test_normalize_header(self) -> None:
        self.assertEqual(normalize_header("Mã SV"), "ma_sv")
        self.assertEqual(normalize_header("Ngày sinh"), "ngay_sinh")
        self.assertEqual(normalize_header("Họ và tên"), "ho_va_ten")
        self.assertEqual(normalize_header("  STT  "), "stt")
        self.assertEqual(normalize_header("Ma-SV.Lop"), "ma_sv_lop")
        self.assertEqual(normalize_header("Ma___SV"), "ma_sv")
        self.assertEqual(normalize_header(""), "")

    def test_escape_cell(self) -> None:
        self.assertEqual(escape_cell("=1+1"), "'=1+1")
        self.assertEqual(escape_cell("+cmd"), "'+cmd")
        self.assertEqual(escape_cell("-cmd"), "'-cmd")
        self.assertEqual(escape_cell("@sum"), "'@sum")
        self.assertEqual(escape_cell("\tcmd"), "'\tcmd")
        self.assertEqual(escape_cell("\rcmd"), "'\rcmd")
        self.assertEqual(escape_cell("  =cmd"), "'  =cmd")
        self.assertEqual(escape_cell("normal"), "normal")
        self.assertEqual(escape_cell(123), 123)
        self.assertIsNone(escape_cell(None))

    def test_write_csv(self) -> None:
        headers = ["Mã SV", "Lệnh"]
        rows = [["B23DCAT001", "=cmd"], ["B23DCAT002", None]]
        data = write_csv(headers, rows)

        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        text = data.decode("utf-8-sig")
        self.assertIn("'=cmd", text)
        self.assertIn("B23DCAT001", text)
        self.assertIn("B23DCAT002", text)

    def test_read_csv_utf8_sig_and_accents(self) -> None:
        csv_text = "\ufeffMã SV,Họ và tên\nB23DCAT001,Nguyễn Văn A\n"
        headers, rows = read_table("sinh_vien.csv", csv_text.encode("utf-8"))
        self.assertEqual(headers, ["ma_sv", "ho_va_ten"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ma_sv"], "B23DCAT001")
        self.assertEqual(rows[0]["ho_va_ten"], "Nguyễn Văn A")
        self.assertEqual(rows[0]["__row__"], 2)

    def test_read_csv_semicolon_and_cp1258(self) -> None:
        csv_semicolon = "Mã SV;Họ và tên\nB23DCAT001;Nguyễn Văn B\n"
        headers, rows = read_table("sinh_vien.csv", csv_semicolon.encode("utf-8"))
        self.assertEqual(headers, ["ma_sv", "ho_va_ten"])
        self.assertEqual(rows[0]["ho_va_ten"], "Nguyễn Văn B")

        # cp1258 encoding with combining tilde (\xde)
        cp1258_bytes = b"Ma\xde SV,Ho ten\nB23DCAT002,Nguyen Van C\n"
        headers, rows = read_table("sinh_vien.csv", cp1258_bytes)
        self.assertEqual(headers, ["ma_sv", "ho_ten"])
        self.assertEqual(rows[0]["ho_ten"], "Nguyen Van C")

        # Unreadable encoding in both utf-8 and cp1258 (byte 0x81 is undefined in cp1258)
        with self.assertRaises(TabularError) as ctx:
            read_table("sinh_vien.csv", b"Header\n\x81invalid\n")
        self.assertEqual(str(ctx.exception), "Không đọc được bảng mã, hãy lưu tệp dạng CSV UTF-8")

    def test_duplicate_headers_raise_error(self) -> None:
        csv_text = "Mã SV,Ma SV\nB23DCAT001,B23DCAT002\n"
        with self.assertRaises(TabularError) as ctx:
            read_table("test.csv", csv_text.encode("utf-8"))
        self.assertIn("bị trùng", str(ctx.exception))

    def test_limits_max_rows_and_max_bytes_and_cols(self) -> None:
        data = "Mã SV\nB2301\nB2302\nB2303\n".encode("utf-8")
        with self.assertRaises(TabularError) as ctx:
            read_table("test.csv", data, max_rows=2)
        self.assertIn("vượt quá", str(ctx.exception))

        with self.assertRaises(TabularError) as ctx:
            read_table("test.csv", data, max_bytes=5)
        self.assertIn("Tệp vượt quá", str(ctx.exception))

        many_cols = b"c1,c2,c3\n1,2,3\n"
        with self.assertRaises(TabularError) as ctx:
            read_table("test.csv", many_cols, max_cols=2)
        self.assertIn("Số cột", str(ctx.exception))

    def test_unsupported_extension_and_bad_xlsx(self) -> None:
        with self.assertRaises(TabularError) as ctx:
            read_table("test.txt", b"header\nval\n")
        self.assertIn("không được hỗ trợ", str(ctx.exception))

        with self.assertRaises(TabularError) as ctx:
            read_table("test.xlsx", b"not a valid zip file")
        self.assertEqual(str(ctx.exception), "Tệp Excel hỏng hoặc không đúng định dạng .xlsx")

    def test_empty_data_raises_error(self) -> None:
        with self.assertRaises(TabularError) as ctx:
            read_table("test.csv", "Mã SV,Họ tên\n".encode("utf-8"))
        self.assertEqual(str(ctx.exception), "Tệp không có dữ liệu")

        with self.assertRaises(TabularError) as ctx:
            read_table("test.csv", b"\n\n   \n")
        self.assertEqual(str(ctx.exception), "Tệp không có dữ liệu")

    def test_row_number_with_blank_lines(self) -> None:
        csv_text = "Mã SV,Họ tên\n\nB2301,Nguyễn A\n   \nB2302,Nguyễn B\n"
        _, rows = read_table("test.csv", csv_text.encode("utf-8"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["__row__"], 3)
        self.assertEqual(rows[1]["__row__"], 5)

        # XLSX with blank row
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.cell(row=1, column=1, value="Mã SV")
        ws.cell(row=1, column=2, value="Họ tên")
        # row 2 blank
        ws.cell(row=3, column=1, value="B2301")
        ws.cell(row=3, column=2, value="Nguyễn A")

        buf = io.BytesIO()
        wb.save(buf)
        _, xlsx_rows = read_table("test.xlsx", buf.getvalue())
        self.assertEqual(len(xlsx_rows), 1)
        self.assertEqual(xlsx_rows[0]["__row__"], 3)

    def test_write_xlsx_round_trip_and_date(self) -> None:
        headers = ["Mã SV", "Họ và tên", "Ngày sinh", "Giờ học", "Số tiết", "Ghi chú"]
        rows = [
            [
                "B23DCAT001",
                "Nguyễn Văn A",
                datetime.date(2005, 1, 1),
                datetime.time(7, 30),
                5.0,
                None,
            ]
        ]
        xlsx_bytes = write_xlsx(headers, rows, sheet_name="Lớp học IoT và ứng dụng dài hơn 31 ký tự")
        out_headers, out_rows = read_table("test.xlsx", xlsx_bytes)

        self.assertEqual(
            out_headers,
            ["ma_sv", "ho_va_ten", "ngay_sinh", "gio_hoc", "so_tiet", "ghi_chu"],
        )
        self.assertEqual(len(out_rows), 1)
        row = out_rows[0]
        self.assertEqual(row["ma_sv"], "B23DCAT001")
        self.assertEqual(row["ho_va_ten"], "Nguyễn Văn A")
        self.assertEqual(row["ngay_sinh"], "01/01/2005")
        self.assertEqual(row["gio_hoc"], "07:30")
        self.assertEqual(row["so_tiet"], "5")
        self.assertEqual(row["ghi_chu"], "")
        self.assertEqual(row["__row__"], 2)

    def test_datetime_formatting_in_xlsx(self) -> None:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Mã", "Ngày hẹn", "Buổi hẹn"])
        ws.append(["T1", datetime.datetime(2026, 11, 7, 0, 0, 0), datetime.datetime(2026, 11, 7, 14, 30, 0)])

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        _, rows = read_table("appointment.xlsx", buf.getvalue())
        self.assertEqual(rows[0]["ngay_hen"], "07/11/2026")
        self.assertEqual(rows[0]["buoi_hen"], "07/11/2026 14:30")

    def test_empty_header_column_dropped(self) -> None:
        csv_text = "Mã SV,,Họ và tên,   ,Lớp\nB2301,x,Nguyễn A,y,D23\n"
        headers, rows = read_table("test.csv", csv_text.encode("utf-8"))
        self.assertEqual(headers, ["ma_sv", "ho_va_ten", "lop"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0], {"ma_sv": "B2301", "ho_va_ten": "Nguyễn A", "lop": "D23", "__row__": 2})


if __name__ == "__main__":
    unittest.main()
