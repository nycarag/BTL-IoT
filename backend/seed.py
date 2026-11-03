"""Seed classes, students, active session, default devices and face biometric references."""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path

import numpy as np
from sqlalchemy import select

from app.core.domain import validate_roster
from app.database import SessionLocal, init_db
from app.models import ClassRoom, Student, AttendanceSession, Device
from app.models.school import DeviceConfig, FaceReference, utcnow

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
ROSTER_PATH = ROOT / "data" / "class_roster.json"
FACES_DIR = ROOT / "data" / "faces"


def extract_student_code_from_filename(filename: str) -> str | None:
    stem = Path(filename).stem
    parts = stem.split("_")
    for part in parts:
        p = part.strip().upper()
        if p.startswith("B23") or p.startswith("B22") or p.startswith("B21"):
            return p
    # Fallback by name mapping if needed
    if "KHOA" in stem.upper():
        return "B23DCAT153"
    if "KIEN" in stem.upper():
        return "B23DCAT156"
    if "CUONG" in stem.upper():
        return "B23DCAT034"
    if "HAI" in stem.upper():
        return "B23DCAT093"
    if "TUAN" in stem.upper():
        return "B23DCAT320"
    return None


def main() -> None:
    init_db()
    roster = validate_roster(json.loads(ROSTER_PATH.read_text(encoding="utf-8")))

    with SessionLocal() as db:
        # 1. Seed classes and students
        classes = {item.code: item for item in db.scalars(select(ClassRoom))}
        for raw in roster:
            class_code = raw["class"]
            classroom = classes.get(class_code)
            if not classroom:
                classroom = ClassRoom(code=class_code, name=f"Lớp {class_code}")
                db.add(classroom)
                db.flush()
                classes[class_code] = classroom
            student_code = raw["id"].strip().upper()
            student = db.scalar(select(Student).where(Student.student_code == student_code))
            if not student:
                student = Student(
                    student_code=student_code, name=raw["name"],
                    date_of_birth=raw.get("dob"), class_id=classroom.id,
                )
                db.add(student)
        db.commit()

        # 2. Ensure default class & active session
        target_class = db.scalar(select(ClassRoom).where(ClassRoom.code == "D23CTAT01-B"))
        if not target_class:
            target_class = db.scalar(select(ClassRoom))

        session = db.scalar(select(AttendanceSession).where(
            AttendanceSession.class_id == target_class.id,
            AttendanceSession.status == "open"
        ))
        if not session:
            session = AttendanceSession(
                class_id=target_class.id,
                title="Phiên điểm danh IoT - Nhóm 05 (D23CTAT01-B)",
                status="open",
                starts_at=utcnow()
            )
            db.add(session)
            db.flush()

        # 3. Seed default devices and bind to session with optimal ROI
        for dev_id, dev_name in [("esp32-cam-01", "ESP32-CAM Kiosk (Nhóm 05)"), ("webcam-01", "Laptop Webcam Local")]:
            device = db.get(Device, dev_id)
            if not device:
                device = Device(id=dev_id, name=dev_name, status="online", last_seen=utcnow())
                db.add(device)
            else:
                device.status = "online"
                device.last_seen = utcnow()
            db.flush()

            cfg = db.get(DeviceConfig, dev_id)
            if not cfg:
                cfg = DeviceConfig(
                    device_id=dev_id,
                    session_id=session.id,
                    roi_left=0.15,
                    roi_top=0.10,
                    roi_right=0.85,
                    roi_bottom=0.90
                )
                db.add(cfg)
            else:
                cfg.session_id = session.id
        db.commit()

        # 4. Auto-enroll face biometric vectors from data/faces/
        try:
            import face_recognition
            print("Detecting face photos in data/faces/ and generating 128D embeddings...")
            enrolled_count = 0
            student_encodings: dict[str, list[np.ndarray]] = {}

            for img_file in FACES_DIR.glob("*.jpg"):
                code = extract_student_code_from_filename(img_file.name)
                if not code:
                    continue
                try:
                    img = face_recognition.load_image_file(str(img_file))
                    encs = face_recognition.face_encodings(img)
                    if encs:
                        student_encodings.setdefault(code, []).append(encs[0])
                except Exception as e:
                    logger.warning(f"Failed encoding {img_file.name}: {e}")

            for code, enc_list in student_encodings.items():
                student = db.scalar(select(Student).where(Student.student_code == code))
                if not student:
                    continue
                # Lưu tất cả các vector thô dưới dạng list-of-lists (không chuẩn hóa L2)
                raw_vectors = [v.tolist() for v in enc_list]
                embedding_json = json.dumps(raw_vectors)

                ref = db.get(FaceReference, student.id)
                if not ref:
                    ref = FaceReference(
                        student_id=student.id,
                        embedding=embedding_json,
                        enrolled_by="system_auto_seed",
                        consent_at=utcnow()
                    )
                    db.add(ref)
                else:
                    ref.embedding = embedding_json
                    ref.consent_at = utcnow()
                enrolled_count += 1
                print(f"  -> Enrolled face for {code}: {student.name} ({len(enc_list)} photo samples)")

            db.commit()
            print(f"Successfully auto-enrolled {enrolled_count} student face references!")
        except ImportError:
            print("Notice: face_recognition not available; skipped biometric vector seeding.")

        print(f"Seeded {len(roster)} students into database.")
        print(f"Active Session: #{session.id} - '{session.title}'")


if __name__ == "__main__":
    main()
