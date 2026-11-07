"""Schemas for class schedules."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScheduleInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    class_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=255)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    start_time: str = Field(pattern=r"^\d{1,2}:\d{2}$")
    end_time: str = Field(pattern=r"^\d{1,2}:\d{2}$")
    room: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_times(self) -> ScheduleInput:
        try:
            d = date.fromisoformat(self.date)
        except ValueError as exc:
            raise ValueError(f"Ngày không hợp lệ: {self.date}") from exc

        def _parse(t_str: str) -> time:
            parts = t_str.split(":")
            h, m = int(parts[0]), int(parts[1])
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError(f"Giờ không hợp lệ: {t_str}")
            return time(h, m)

        t_start = _parse(self.start_time)
        t_end = _parse(self.end_time)

        # Chuẩn hóa về dạng HH:MM
        self.start_time = f"{t_start.hour:02d}:{t_start.minute:02d}"
        self.end_time = f"{t_end.hour:02d}:{t_end.minute:02d}"

        if t_end <= t_start:
            raise ValueError("Giờ kết thúc phải sau giờ bắt đầu")

        dt_start = datetime.combine(d, t_start)
        dt_end = datetime.combine(d, t_end)
        if (dt_end - dt_start) > timedelta(hours=6):
            raise ValueError("Độ dài buổi học không được vượt quá 6 giờ")

        return self


class ScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    class_id: int
    class_code: str
    title: str
    date: str
    start_time: str
    end_time: str
    room: str | None = None
    note: str | None = None
    session_id: int | None = None
    session_status: str | None = None
