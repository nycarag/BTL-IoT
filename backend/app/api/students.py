import json
import numpy as np

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import verify_token
from app.database import get_db
from app.models import Attendance, ClassRoom, Student
from app.models.school import FaceReference, utcnow
from app.schemas import StudentCreate, StudentResponse
from app.services.face_recognition import FaceRecognitionAdapter
from app.services.images import validate_image
from starlette.concurrency import run_in_threadpool

router = APIRouter()


def student_response(student, db):
    return dict(id=student.id, student_code=student.student_code, name=student.name,
                date_of_birth=student.date_of_birth, class_id=student.class_id,
                enrolled=db.get(FaceReference, student.id) is not None)


def save_student(payload, db, student=None):
    if payload.class_id is not None and not db.get(ClassRoom, payload.class_id):
        raise HTTPException(404, "Class not found")
    values = payload.model_dump()
    values["student_code"] = values["student_code"].upper()
    if student is None:
        student = Student(**values)
        db.add(student)
    else:
        for key, value in values.items():
            setattr(student, key, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Student code already exists")
    return student_response(student, db)


@router.get("/students", response_model=list[StudentResponse])
def list_students(_: str = Depends(verify_token), db: Session = Depends(get_db)):
    stmt = (
        select(Student, FaceReference.student_id.is_not(None))
        .outerjoin(FaceReference, Student.id == FaceReference.student_id)
        .order_by(Student.student_code)
    )
    return [
        dict(
            id=s.id,
            student_code=s.student_code,
            name=s.name,
            date_of_birth=s.date_of_birth,
            class_id=s.class_id,
            enrolled=bool(enrolled),
        )
        for s, enrolled in db.execute(stmt)
    ]


@router.post("/students", response_model=StudentResponse, status_code=201)
def create_student(payload: StudentCreate, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    return save_student(payload, db)


@router.put("/students/{student_id}", response_model=StudentResponse)
def update_student(student_id: int, payload: StudentCreate, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(404, "Student not found")
    return save_student(payload, db, student)


@router.delete("/students/{student_id}", status_code=204)
def delete_student(student_id: int, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(404, "Student not found")
    if db.scalar(select(Attendance.id).where(Attendance.student_id == student_id)):
        raise HTTPException(409, "Student has attendance history; delete biometric reference instead")
    reference = db.get(FaceReference, student_id)
    if reference:
        db.delete(reference)
        db.flush()
    db.delete(student)
    db.commit()


@router.post("/students/{student_id}/face")
async def enroll_face(
    student_id: int,
    image: list[UploadFile] | UploadFile = File(...),
    consent: bool = Form(...),
    username: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    if not consent:
        raise HTTPException(422, "Explicit biometric consent is required")
    if db.get(Student, student_id) is None:
        raise HTTPException(404, "Student not found")
    
    file_list = image if isinstance(image, list) else [image]
    if not file_list:
        raise HTTPException(422, "Vui lòng chọn ít nhất một tệp ảnh chân dung")
    if len(file_list) > 5:
        raise HTTPException(422, "Chỉ được tải lên tối đa 5 ảnh chân dung")

    recognizer = FaceRecognitionAdapter()
    if recognizer.engine is None:
        raise HTTPException(503, recognizer.reason)

    enc_list = []
    for f in file_list:
        if f.content_type not in {"image/jpeg", "image/png"}:
            raise HTTPException(415, f"Tệp {f.filename or ''} không đúng định dạng. Chỉ chấp nhận JPEG và PNG.")
        body = await f.read(5 * 1024 * 1024 + 1)
        if len(body) > 5 * 1024 * 1024:
            raise HTTPException(413, f"Ảnh {f.filename or ''} vượt quá dung lượng 5 MiB")
        try:
            validate_image(body)
            vec = await run_in_threadpool(recognizer.encode, body)
            enc_list.append(vec)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        except Exception as exc:
            raise HTTPException(422, f"Lỗi xử lý ảnh {f.filename or ''}: {str(exc)}")

    if not enc_list:
        raise HTTPException(422, "Không trích xuất được vector khuôn mặt hợp lệ.")

    # Tính vector trung bình chuẩn hóa nếu có nhiều mẫu ảnh (chuẩn nhận diện đa góc nhìn)
    avg_vec = np.mean(enc_list, axis=0)
    norm = np.linalg.norm(avg_vec)
    if norm > 0:
        avg_vec = avg_vec / norm

    reference = db.get(FaceReference, student_id)
    if reference is None:
        reference = FaceReference(student_id=student_id, enrolled_by=username, embedding="")
        db.add(reference)
    reference.embedding = json.dumps(avg_vec.tolist())
    reference.consent_at = utcnow()
    reference.enrolled_by = username
    db.commit()
    return {"enrolled": True, "samples": len(enc_list), "raw_image_stored": False}


@router.delete("/students/{student_id}/face", status_code=204)
def delete_face(student_id: int, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    if db.get(Student, student_id) is None:
        raise HTTPException(404, "Student not found")
    reference = db.get(FaceReference, student_id)
    if reference:
        db.delete(reference)
        db.commit()
