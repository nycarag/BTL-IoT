"""Tests for roster import and export API (CSV, XLSX, JSON)."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ["ADMIN_PASSWORD"] = "test-password-only"
os.environ["DEVICE_TOKEN"] = "test-device-only"
os.environ["FRAME_INTERVAL_SECONDS"] = "0"

from fastapi.testclient import TestClient
import openpyxl
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.api import roster_io
from app.database import Base, get_db
from app.main import create_app
from app.models.school import AuditLog, ClassRoom, FaceReference, Student


class RosterIoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{self.temp.name}/test.db",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(self.engine, expire_on_commit=False)

        app = create_app()
        app.include_router(roster_io.router, prefix="/api")
        # Đảm bảo Mount của StaticFiles luôn nằm cuối cùng để không chặn các route API mới
        mounts = [r for r in app.routes if type(r).__name__ == "Mount"]
        for m in mounts:
            app.routes.remove(m)
            app.routes.append(m)

        def override_db():
            with self.factory() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

        # Login admin to obtain access token
        resp = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "test-password-only"},
        )
        token = resp.json()["access_token"]
        self.auth = {"Authorization": f"Bearer {token}"}

        # Seed initial class and student
        with self.factory() as db:
            cls = ClassRoom(code="D23CTAT01-B", name="D23 An Toan Thong Tin B")
            db.add(cls)
            db.flush()
            self.class_id = cls.id

            st1 = Student(
                student_code="B23DCAT001",
                name="Nguyễn Văn A",
                date_of_birth="01/01/2005",
                class_id=cls.id,
            )
            st2 = Student(
                student_code="B23DCAT002",
                name="Trần Thị B",
                date_of_birth="15/05/2005",
                class_id=cls.id,
            )
            db.add_all([st1, st2])
            db.flush()

            # Enrolled face for st1
            db.add(
                FaceReference(
                    student_id=st1.id,
                    embedding=json.dumps([0.1] * 128),
                    enrolled_by="admin",
                )
            )
            db.commit()

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.temp.cleanup()

    def test_export_csv_structure_and_no_embedding(self):
        """Export CSV: có BOM, có tiêu đề tiếng Việt, đúng số dòng, không có chữ 'embedding'."""
        res = self.client.get("/api/students/export?format=csv", headers=self.auth)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers["content-type"], "text/csv; charset=utf-8")
        self.assertIn("attachment; filename=", res.headers["content-disposition"])
        self.assertTrue(res.headers["content-disposition"].endswith('.csv"'))

        # Có BOM UTF-8 (utf-8-sig)
        self.assertTrue(res.content.startswith(b"\xef\xbb\xbf"))

        text = res.content.decode("utf-8-sig")
        lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
        self.assertEqual(len(lines), 3)  # 1 dòng tiêu đề + 2 dòng sinh viên

        # Kiểm tra tiêu đề tiếng Việt
        self.assertEqual(
            lines[0],
            "STT,Mã SV,Họ và tên,Ngày sinh,Mã lớp,Đã đăng ký khuôn mặt",
        )

        # Dữ liệu sinh viên sắp xếp theo Mã SV
        self.assertIn("B23DCAT001,Nguyễn Văn A,01/01/2005,D23CTAT01-B,Có", lines[1])
        self.assertIn("B23DCAT002,Trần Thị B,15/05/2005,D23CTAT01-B,Không", lines[2])

        # Tuyệt đối không xuất embedding
        self.assertNotIn("embedding", text.lower())

        # Kiểm tra bản ghi AuditLog
        with self.factory() as db:
            logs = db.scalars(
                select(AuditLog).where(AuditLog.action == "students.export")
            ).all()
            self.assertEqual(len(logs), 1)
            detail = json.loads(logs[0].detail)
            self.assertEqual(detail["format"], "csv")
            self.assertEqual(detail["count"], 2)

    def test_export_csv_by_class_id_and_not_found(self):
        """Export CSV theo class_id cụ thể, báo 404 khi class_id không tồn tại."""
        res = self.client.get(
            f"/api/students/export?format=csv&class_id={self.class_id}",
            headers=self.auth,
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("sinh_vien_D23CTAT01-B_", res.headers["content-disposition"])

        res_404 = self.client.get(
            "/api/students/export?format=csv&class_id=99999",
            headers=self.auth,
        )
        self.assertEqual(res_404.status_code, 404)
        self.assertIn("Không tìm thấy lớp", res_404.json()["detail"])

    def test_export_formula_injection_escaping(self):
        """Ô '=HYPERLINK(...)' trong tên khi xuất CSV phải thành ''=HYPERLINK(...)'."""
        with self.factory() as db:
            st = Student(
                student_code="B23DCAT999",
                name='=HYPERLINK("http://evil.com","hack")',
                date_of_birth="01/01/2005",
                class_id=self.class_id,
            )
            db.add(st)
            db.commit()

        res = self.client.get("/api/students/export?format=csv", headers=self.auth)
        self.assertEqual(res.status_code, 200)
        text = res.content.decode("utf-8-sig")
        # Phải được chèn dấu ' ở đầu công thức
        self.assertIn("'=HYPERLINK", text)

    def test_export_xlsx_readable_by_openpyxl(self):
        """Export XLSX: mở lại bằng openpyxl được, đúng dữ liệu."""
        res = self.client.get("/api/students/export?format=xlsx", headers=self.auth)
        self.assertEqual(res.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            res.headers["content-type"],
        )

        wb = openpyxl.load_workbook(io.BytesIO(res.content))
        self.assertIn("SinhVien", wb.sheetnames)
        ws = wb["SinhVien"]

        rows = list(ws.iter_rows(values_only=True))
        self.assertEqual(len(rows), 3)
        self.assertEqual(
            rows[0],
            ("STT", "Mã SV", "Họ và tên", "Ngày sinh", "Mã lớp", "Đã đăng ký khuôn mặt"),
        )
        self.assertEqual(rows[1][1], "B23DCAT001")
        self.assertEqual(rows[1][5], "Có")
        self.assertEqual(rows[2][1], "B23DCAT002")
        self.assertEqual(rows[2][5], "Không")

    def test_import_template_csv_and_xlsx(self):
        """GET /api/students/import-template có dòng ví dụ và mở được."""
        res_csv = self.client.get("/api/students/import-template?format=csv", headers=self.auth)
        self.assertEqual(res_csv.status_code, 200)
        text = res_csv.content.decode("utf-8-sig")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], "STT,Mã SV,Họ và tên,Ngày sinh,Mã lớp")
        self.assertIn("B23DCAT999,Nguyễn Văn Mẫu,01/01/2005,D23CTAT01-B", lines[1])
        # Không có cột khuôn mặt
        self.assertNotIn("khuôn mặt", text.lower())

        res_xlsx = self.client.get("/api/students/import-template?format=xlsx", headers=self.auth)
        self.assertEqual(res_xlsx.status_code, 200)
        wb = openpyxl.load_workbook(io.BytesIO(res_xlsx.content))
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][1], "B23DCAT999")

    def test_import_csv_preview_does_not_modify_db(self):
        """Import CSV preview: không ghi DB, created tính đúng."""
        csv_content = (
            "Mã SV,Họ và tên,Ngày sinh,Mã lớp\n"
            "B23DCAT003,Lê Hoàng Nam,03/03/2005,D23CTAT01-B\n"
            "B23DCAT004,Phạm Đức Minh,04/04/2005,D23CTAT01-B\n"
        )
        with self.factory() as db:
            before_count = db.query(Student).count()

        res = self.client.post(
            "/api/students/import",
            headers=self.auth,
            data={"mode": "preview", "on_conflict": "skip"},
            files={"file": ("roster.csv", csv_content.encode("utf-8"), "text/csv")},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["mode"], "preview")
        self.assertEqual(data["total_rows"], 2)
        self.assertEqual(data["valid_rows"], 2)
        self.assertEqual(data["created"], 2)
        self.assertEqual(data["errors"], [])
        self.assertEqual(len(data["rows"]), 2)

        with self.factory() as db:
            after_count = db.query(Student).count()
        self.assertEqual(before_count, after_count)

    def test_import_commit_valid_and_reimport_skip_and_update(self):
        """Import commit hợp lệ: ghi đủ; import lại cùng file với skip -> created=0, skipped=N; với update -> updated=N."""
        csv_content = (
            "Mã SV,Họ và tên,Ngày sinh,Mã lớp\n"
            "B23DCAT010,Trần Văn Cường,10/10/2005,D23CTAT01-B\n"
            "B23DCAT011,Ngô Thị Dung,11/11/2005,D23CTAT01-B\n"
        )
        # Commit lần 1 -> created = 2
        res1 = self.client.post(
            "/api/students/import",
            headers=self.auth,
            data={"mode": "commit", "on_conflict": "skip"},
            files={"file": ("roster.csv", csv_content.encode("utf-8"), "text/csv")},
        )
        self.assertEqual(res1.status_code, 200)
        data1 = res1.json()
        self.assertEqual(data1["created"], 2)
        self.assertEqual(data1["skipped"], 0)
        self.assertEqual(data1["updated"], 0)

        with self.factory() as db:
            st = db.scalars(
                select(Student).where(Student.student_code == "B23DCAT010")
            ).first()
            self.assertIsNotNone(st)
            self.assertEqual(st.name, "Trần Văn Cường")

        # Import lại cùng file với on_conflict=skip -> created=0, skipped=2
        res2 = self.client.post(
            "/api/students/import",
            headers=self.auth,
            data={"mode": "commit", "on_conflict": "skip"},
            files={"file": ("roster.csv", csv_content.encode("utf-8"), "text/csv")},
        )
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()
        self.assertEqual(data2["created"], 0)
        self.assertEqual(data2["skipped"], 2)
        self.assertEqual(data2["updated"], 0)

        # Import lại với on_conflict=update và đổi tên -> updated=2
        csv_updated = (
            "Mã SV,Họ và tên,Ngày sinh,Mã lớp\n"
            "B23DCAT010,Trần Văn Cường Đổi Tên,10/10/2005,D23CTAT01-B\n"
            "B23DCAT011,Ngô Thị Dung Đổi Tên,11/11/2005,D23CTAT01-B\n"
        )
        res3 = self.client.post(
            "/api/students/import",
            headers=self.auth,
            data={"mode": "commit", "on_conflict": "update"},
            files={"file": ("roster.csv", csv_updated.encode("utf-8"), "text/csv")},
        )
        self.assertEqual(res3.status_code, 200)
        data3 = res3.json()
        self.assertEqual(data3["created"], 0)
        self.assertEqual(data3["skipped"], 0)
        self.assertEqual(data3["updated"], 2)

        with self.factory() as db:
            st_up = db.scalars(
                select(Student).where(Student.student_code == "B23DCAT010")
            ).first()
            self.assertEqual(st_up.name, "Trần Văn Cường Đổi Tên")

    def test_import_one_error_row_in_commit_returns_422_and_rolls_back(self):
        """Import có 1 dòng lỗi + commit -> 422, DB không đổi (đếm số SV trước và sau)."""
        csv_content = (
            "Mã SV,Họ và tên,Ngày sinh,Mã lớp\n"
            "B23DCAT020,Sinh Viên Đúng,01/01/2005,D23CTAT01-B\n"
            "B23DCAT021,Sinh Viên Sai Ngày,31/02/2005,D23CTAT01-B\n"
        )
        with self.factory() as db:
            before_count = db.query(Student).count()

        res = self.client.post(
            "/api/students/import",
            headers=self.auth,
            data={"mode": "commit", "on_conflict": "skip"},
            files={"file": ("roster.csv", csv_content.encode("utf-8"), "text/csv")},
        )
        self.assertEqual(res.status_code, 422)
        data = res.json()
        self.assertEqual(len(data["errors"]), 1)
        self.assertEqual(data["errors"][0]["row"], 3)
        self.assertEqual(data["errors"][0]["field"], "date_of_birth")

        with self.factory() as db:
            after_count = db.query(Student).count()
            st = db.scalars(
                select(Student).where(Student.student_code == "B23DCAT020")
            ).first()
            self.assertIsNone(st)  # Không được ghi dòng hợp lệ nào vào DB!
        self.assertEqual(before_count, after_count)

    def test_validation_duplicate_code_date_and_create_missing_classes(self):
        """Mã trùng trong file, ngày sai 31/02/2005, lớp không tồn tại (và create_missing_classes=true thì tạo lớp)."""
        csv_content = (
            "Mã SV,Họ và tên,Ngày sinh,Mã lớp\n"
            "B23DCAT030,Sinh Viên Đầu,01/01/2005,D23CTAT01-B\n"
            "B23DCAT030,Sinh Viên Trùng Mã,02/02/2005,D23CTAT01-B\n"
            "B23DCAT031,Sinh Viên Lớp Lạ,01/01/2005,LOP_CHUA_CO\n"
        )
        # Khi create_missing_classes=false -> lỗi cả trùng mã lẫn lớp chưa có
        res = self.client.post(
            "/api/students/import",
            headers=self.auth,
            data={"mode": "preview", "create_missing_classes": "false"},
            files={"file": ("roster.csv", csv_content.encode("utf-8"), "text/csv")},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        err_fields = [e["field"] for e in data["errors"]]
        self.assertIn("student_code", err_fields)
        self.assertIn("class_code", err_fields)

        # Lỗi trùng mã phải nói rõ trùng với dòng 2
        dup_err = next(e for e in data["errors"] if e["field"] == "student_code")
        self.assertEqual(dup_err["row"], 3)
        self.assertIn("trùng với dòng 2", dup_err["message"])

        # Kiểm tra create_missing_classes=true tạo lớp mới
        csv_new_class = (
            "Mã SV,Họ và tên,Ngày sinh,Mã lớp\n"
            "B23DCAT040,Sinh Viên Lớp Mới,01/01/2005,D23CNTT01-A\n"
        )
        res_create = self.client.post(
            "/api/students/import",
            headers=self.auth,
            data={"mode": "commit", "create_missing_classes": "true"},
            files={"file": ("roster.csv", csv_new_class.encode("utf-8"), "text/csv")},
        )
        self.assertEqual(res_create.status_code, 200)
        self.assertEqual(res_create.json()["created"], 1)

        with self.factory() as db:
            new_cls = db.scalars(
                select(ClassRoom).where(ClassRoom.code == "D23CNTT01-A")
            ).first()
            self.assertIsNotNone(new_cls)
            self.assertEqual(new_cls.name, "D23CNTT01-A")
            st = db.scalars(
                select(Student).where(Student.student_code == "B23DCAT040")
            ).first()
            self.assertEqual(st.class_id, new_cls.id)

    def test_import_json_data_roster(self):
        """Import file .json đúng format data/class_roster.json -> 36 dòng hợp lệ khi create_missing_classes=true."""
        roster_path = Path("/home/nycarag/Projects/BTL-IoT/data/class_roster.json")
        self.assertTrue(roster_path.exists())
        with open(roster_path, "rb") as f:
            json_bytes = f.read()

        res = self.client.post(
            "/api/students/import",
            headers=self.auth,
            data={"mode": "commit", "create_missing_classes": "true"},
            files={"file": ("class_roster.json", json_bytes, "application/json")},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total_rows"], 36)
        self.assertEqual(data["valid_rows"], 36)
        self.assertEqual(data["created"], 36)
        self.assertEqual(data["errors"], [])

        with self.factory() as db:
            # 2 SV khởi tạo ban đầu + 36 SV mới
            count = db.query(Student).count()
            self.assertEqual(count, 38)

    def test_file_size_extension_and_auth_guards(self):
        """File 2 MiB + 1 byte -> 413; đuôi .txt -> 415; không có token -> 401."""
        # 1. Quá 2 MiB -> 413
        big_content = b"a" * (2 * 1024 * 1024 + 1)
        res_413 = self.client.post(
            "/api/students/import",
            headers=self.auth,
            files={"file": ("large.csv", big_content, "text/csv")},
        )
        self.assertEqual(res_413.status_code, 413)

        # 2. Đuôi .txt -> 415
        res_415 = self.client.post(
            "/api/students/import",
            headers=self.auth,
            files={"file": ("roster.txt", b"dummy content", "text/plain")},
        )
        self.assertEqual(res_415.status_code, 415)

        # 3. Không có token -> 401
        res_401 = self.client.post(
            "/api/students/import",
            files={"file": ("roster.csv", b"dummy content", "text/csv")},
        )
        self.assertEqual(res_401.status_code, 401)

    def test_audit_log_after_import_commit(self):
        """Có bản ghi AuditLog action students.import sau commit."""
        csv_content = (
            "Mã SV,Họ và tên,Ngày sinh,Mã lớp\n"
            "B23DCAT050,Kiểm Tra Audit,05/05/2005,D23CTAT01-B\n"
        )
        res = self.client.post(
            "/api/students/import",
            headers=self.auth,
            data={"mode": "commit"},
            files={"file": ("audit_test.csv", csv_content.encode("utf-8"), "text/csv")},
        )
        self.assertEqual(res.status_code, 200)

        with self.factory() as db:
            logs = db.scalars(
                select(AuditLog).where(AuditLog.action == "students.import")
            ).all()
            self.assertTrue(len(logs) >= 1)
            latest = logs[-1]
            self.assertEqual(latest.actor, "admin")
            detail = json.loads(latest.detail)
            self.assertEqual(detail["filename"], "audit_test.csv")
            self.assertEqual(detail["created"], 1)

    def test_reimport_exported_file_no_duplicates(self):
        """Nghiệm thu: nhập lại file vừa xuất không tạo bản ghi trùng."""
        # 1. Xuất danh sách sinh viên hiện tại ra CSV
        res_exp = self.client.get("/api/students/export?format=csv", headers=self.auth)
        self.assertEqual(res_exp.status_code, 200)
        csv_bytes = res_exp.content

        with self.factory() as db:
            count_before = db.query(Student).count()

        # 2. Nhập lại chính file vừa xuất với on_conflict=skip
        res_imp = self.client.post(
            "/api/students/import",
            headers=self.auth,
            data={"mode": "commit", "on_conflict": "skip"},
            files={"file": ("export_reimport.csv", csv_bytes, "text/csv")},
        )
        self.assertEqual(res_imp.status_code, 200)
        data = res_imp.json()
        self.assertEqual(data["created"], 0)
        self.assertEqual(data["skipped"], count_before)
        self.assertEqual(data["updated"], 0)
        self.assertEqual(data["errors"], [])

        # 3. Xác nhận số lượng bản ghi trong cơ sở dữ liệu không đổi
        with self.factory() as db:
            count_after = db.query(Student).count()
        self.assertEqual(count_before, count_after)

