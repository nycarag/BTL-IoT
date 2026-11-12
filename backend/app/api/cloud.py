"""API endpoints for Gateway -> Cloud synchronization."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.security import verify_token
from app.services import cloud_sync

router = APIRouter()


@router.get("/cloud/status")
def get_cloud_status(_: str = Depends(verify_token)) -> dict:
    """Trả về trạng thái hoạt động của mô-đun đồng bộ cloud."""
    return cloud_sync.status()


@router.post("/cloud/sync-now")
def sync_cloud_now(_: str = Depends(verify_token)) -> dict:
    """Kích hoạt một nhịp đồng bộ ngay lập tức lên cloud trong threadpool."""
    res = dict(cloud_sync.sync_once())
    res.pop("commands", None)
    return res
