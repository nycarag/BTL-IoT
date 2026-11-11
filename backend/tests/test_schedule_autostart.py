"""Lưu lịch đang trong giờ học thì ca điểm danh mở ngay, không chờ nhịp của bộ hẹn giờ."""

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

os.environ["ADMIN_PASSWORD"] = "test-password-only"
os.environ["DEVICE_TOKEN"] = "test-device-only"
os.environ["FRAME_INTERVAL_SECONDS"] = "0"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import create_app

VN_TZ = timezone(timedelta(hours=7), "ICT")


class TestScheduleAutostart(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{self.temp.name}/test.db",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(self.engine, expire_on_commit=False)

        app = create_app()

        def db():
            with self.factory() as session:
                yield session

        app.dependency_overrides[get_db] = db
        self.client = TestClient(app)
        self.token = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "test-password-only"},
        ).json()["access_token"]
        self.auth = {"Authorization": f"Bearer {self.token}"}
        self.class_id = self.client.post(
            "/api/classes", json={"code": "D23CTAT01-B", "name": "Lớp An Toàn 1"}, headers=self.auth
        ).json()["id"]

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.temp.cleanup()

    def _window_around_now(self) -> dict[str, str]:
        """Ngày và giờ (giờ VN) của một buổi học đang diễn ra ngay lúc chạy test."""
        now = datetime.now(VN_TZ)
        if now.hour == 23 and now.minute >= 58:
            self.skipTest("Sát nửa đêm: không dựng được buổi học nằm trọn trong ngày")
        end = "23:59" if now.hour >= 22 else f"{now.hour + 2:02d}:{now.minute:02d}"
        return {"date": now.strftime("%Y-%m-%d"), "start_time": now.strftime("%H:%M"), "end_time": end}

    def _schedule(self, title: str, **when: str) -> dict:
        return {"class_id": self.class_id, "title": title, **when}

    def _sessions(self) -> list[tuple[str, str]]:
        rows = self.client.get("/api/sessions", headers=self.auth).json()
        return [(row["title"], row["status"]) for row in rows]

    def test_schedule_saved_inside_its_window_opens_session_immediately(self):
        when = self._window_around_now()
        res = self.client.post("/api/schedules", json=self._schedule("Demo", **when), headers=self.auth)

        self.assertEqual(res.status_code, 201, res.text)
        self.assertEqual(res.json()["session_status"], "open")
        self.assertIsNotNone(res.json()["session_id"])
        day = datetime.strptime(when["date"], "%Y-%m-%d").strftime("%d/%m/%Y")
        self.assertEqual(self._sessions(), [(f"Demo · {day}", "open")])

    def test_future_schedule_does_not_open_session(self):
        tomorrow = (datetime.now(VN_TZ) + timedelta(days=1)).strftime("%Y-%m-%d")
        res = self.client.post(
            "/api/schedules",
            json=self._schedule("Buổi mai", date=tomorrow, start_time="07:00", end_time="09:00"),
            headers=self.auth,
        )

        self.assertEqual(res.status_code, 201, res.text)
        self.assertIsNone(res.json()["session_id"])
        self.assertIsNone(res.json()["session_status"])
        self.assertEqual(self._sessions(), [])

    def test_moving_schedule_into_current_window_opens_session(self):
        tomorrow = (datetime.now(VN_TZ) + timedelta(days=1)).strftime("%Y-%m-%d")
        schedule_id = self.client.post(
            "/api/schedules",
            json=self._schedule("Dời lịch", date=tomorrow, start_time="07:00", end_time="09:00"),
            headers=self.auth,
        ).json()["id"]

        res = self.client.put(
            f"/api/schedules/{schedule_id}",
            json=self._schedule("Dời lịch", **self._window_around_now()),
            headers=self.auth,
        )

        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["session_status"], "open")
        self.assertEqual([status for _, status in self._sessions()], ["open"])

    def test_imported_schedule_inside_its_window_opens_session(self):
        when = self._window_around_now()
        csv = (
            "ma_lop,ten_buoi,ngay,bat_dau,ket_thuc\n"
            f"D23CTAT01-B,Nhập lịch,{when['date']},{when['start_time']},{when['end_time']}\n"
        )
        res = self.client.post(
            "/api/schedules/import",
            files={"file": ("lich.csv", csv.encode("utf-8"), "text/csv")},
            data={"mode": "commit"},
            headers=self.auth,
        )

        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["created"], 1)
        self.assertEqual([status for _, status in self._sessions()], ["open"])

    def test_dashboard_watching_another_session_is_told_when_a_session_opens(self):
        """Ca mới mở chưa có ai theo dõi, nên sự kiện phải tới cả màn hình đang xem buổi khác."""
        other = self.client.post(
            "/api/sessions", json={"class_id": self.class_id, "title": "Buổi cũ"}, headers=self.auth
        ).json()["id"]

        with self.client.websocket_connect(f"/ws/sessions/{other}") as ws:
            ws.send_json({"token": self.token})
            self.assertEqual(ws.receive_json(), {"type": "ready"})

            res = self.client.post(
                "/api/schedules", json=self._schedule("Demo", **self._window_around_now()), headers=self.auth
            )
            self.assertEqual(res.status_code, 201, res.text)
            self.assertEqual(ws.receive_json(), {"type": "session", "status": "open"})


if __name__ == "__main__":
    unittest.main()
