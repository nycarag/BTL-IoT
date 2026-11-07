from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    bearer,
    check_admin_password,
    issue_token,
    login_throttle,
    revoke_token,
    verify_token,
)
from app.database import get_db
from app.models import ClassRoom
from app.schemas import ClassCreate, ClassResponse, LoginRequest, TokenResponse
from app.services.audit import client_ip, log_action

router = APIRouter()


@router.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    ip = client_ip(request) or "unknown"
    key = (ip, payload.username.lower())

    remaining = login_throttle.check(key)
    if remaining is not None:
        log_action(
            db,
            actor="anonymous",
            action="auth.login_locked",
            target=payload.username[:64],
            detail={"retry_after": remaining},
            ip_address=client_ip(request),
            commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Đăng nhập sai quá nhiều lần, thử lại sau {remaining} giây",
            headers={"Retry-After": str(remaining)},
        )

    authenticated = (
        payload.username == settings.admin_username
        and check_admin_password(payload.password)
    )

    if not authenticated:
        just_locked = login_throttle.fail(key)
        log_action(
            db,
            actor="anonymous",
            action="auth.login_failed",
            target=payload.username[:64],
            detail={"reason": "invalid_credentials"},
            ip_address=client_ip(request),
            commit=True,
        )
        if just_locked:
            lock_seconds = getattr(settings, "login_lock_seconds", 900)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Đăng nhập sai quá nhiều lần, thử lại sau {lock_seconds} giây",
                headers={"Retry-After": str(lock_seconds)},
            )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    login_throttle.success(key)
    log_action(
        db,
        actor=payload.username[:255],
        action="auth.login",
        target=payload.username[:64],
        detail=None,
        ip_address=client_ip(request),
        commit=True,
    )
    return TokenResponse(access_token=issue_token(payload.username))


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    username: str = Depends(verify_token),
    db: Session = Depends(get_db),
) -> Response:
    if credentials:
        revoke_token(credentials.credentials)
    log_action(
        db,
        actor=username[:255],
        action="auth.logout",
        target=username[:64],
        detail=None,
        ip_address=client_ip(request),
        commit=True,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/classes", response_model=list[ClassResponse])
def list_classes(_: str = Depends(verify_token), db: Session = Depends(get_db)):
    return list(db.scalars(select(ClassRoom).order_by(ClassRoom.code)))


@router.post("/classes", response_model=ClassResponse, status_code=status.HTTP_201_CREATED)
def create_class(payload: ClassCreate, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    if db.scalar(select(ClassRoom).where(ClassRoom.code == payload.code)):
        raise HTTPException(status_code=409, detail="Class code already exists")
    classroom = ClassRoom(code=payload.code, name=payload.name)
    db.add(classroom)
    db.commit()
    db.refresh(classroom)
    return classroom


@router.put("/classes/{class_id}", response_model=ClassResponse)
def update_class(class_id: int, payload: ClassCreate, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    classroom = db.get(ClassRoom, class_id)
    if classroom is None:
        raise HTTPException(404, "Class not found")
    if db.scalar(select(ClassRoom).where(ClassRoom.code == payload.code, ClassRoom.id != class_id)):
        raise HTTPException(409, "Class code already exists")
    classroom.code, classroom.name = payload.code, payload.name
    db.commit()
    return classroom


@router.delete("/classes/{class_id}", status_code=204)
def delete_class(class_id: int, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    classroom = db.get(ClassRoom, class_id)
    if classroom is None:
        raise HTTPException(404, "Class not found")
    if classroom.students or classroom.sessions:
        raise HTTPException(409, "Class still contains students or sessions")
    db.delete(classroom)
    db.commit()
