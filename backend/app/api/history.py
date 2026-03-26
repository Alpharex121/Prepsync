from fastapi import APIRouter, HTTPException, Query

from app.schemas.history import (
    AttemptRecordRequest,
    AttemptReport,
    HistoryListItem,
    RoomAnalytics,
)
from app.services.history import history_service

router = APIRouter(prefix="/history", tags=["history"])


@router.get("", response_model=list[HistoryListItem])
async def list_history(
    mode: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    topic: str | None = Query(default=None),
    exam: str | None = Query(default=None),
) -> list[HistoryListItem]:
    return history_service.list_history(mode=mode, date_from=date_from, date_to=date_to, topic=topic, exam=exam)


@router.post("/attempt")
async def record_attempt(payload: AttemptRecordRequest) -> dict[str, bool]:
    ok = history_service.record_attempt_submission(
        room_id=payload.room_id,
        user_id=payload.user_id,
        question_index=payload.question_index,
        selected_option=payload.selected_option,
        time_taken_ms=payload.time_taken_ms,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Session or question not found")
    return {"ok": True}


@router.get("/{room_id}/report", response_model=AttemptReport)
async def get_report(room_id: str, user_id: str = Query(...)) -> AttemptReport:
    report = history_service.get_attempt_report(room_id=room_id, user_id=user_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.get("/{room_id}/analytics", response_model=RoomAnalytics)
async def get_analytics(room_id: str) -> RoomAnalytics:
    analytics = history_service.get_room_analytics(room_id)
    if analytics is None:
        raise HTTPException(status_code=404, detail="Analytics not found")
    return analytics
