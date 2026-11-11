from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.security import verify_token
from app.database import get_db
from app.models import AttendanceSession, ClassRoom
from app.schemas import SessionCreate, SessionResponse
from app.services import session_lifecycle
from app.services.websocket import manager

router = APIRouter()


@router.get("/sessions", response_model=list[SessionResponse])
def list_sessions(_: str = Depends(verify_token), db: Session = Depends(get_db)):
    return list(db.scalars(select(AttendanceSession).order_by(AttendanceSession.id.desc())))


@router.post("/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(payload: SessionCreate, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    if not db.get(ClassRoom, payload.class_id):
        raise HTTPException(status_code=404, detail="Class not found")
    session = AttendanceSession(class_id=payload.class_id, title=payload.title, status="draft")
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _set_status(session_id: int, target: str, db: Session) -> AttendanceSession:
    db.rollback()
    if db.bind.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
    session = db.get(AttendanceSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    now = datetime.now(timezone.utc)
    try:
        if target == "open":
            session_lifecycle.open_session(db, session, now)
        else:
            session_lifecycle.close_session(db, session, now)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    db.commit()
    db.refresh(session)
    return session


@router.post("/sessions/{session_id}/start", response_model=SessionResponse)
async def start_session(session_id: int, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    session = _set_status(session_id, "open", db)
    await manager.broadcast_all({"type": "session", "status": "open"})
    return session


@router.post("/sessions/{session_id}/close", response_model=SessionResponse)
async def close_session(session_id: int, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    session = _set_status(session_id, "closed", db)
    await manager.broadcast_all({"type": "session", "status": "closed"})
    return session
