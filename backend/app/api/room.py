from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas.room import (
    RoomCreateRequest,
    RoomCreateResponse,
    RoomGenerationResponse,
    RoomJoinCheckResponse,
    RoomStateResponse,
    RoomStatus,
    RoomTransitionRequest,
)
from app.security.rate_limit import rate_limit
from app.services.history import history_service
from app.services.quiz_generator import quiz_generator
from app.services.realtime import get_realtime_engine
from app.services.room import RoomService, get_room_service

router = APIRouter(prefix="/rooms", tags=["rooms"])


@router.post(
    "/create",
    response_model=RoomCreateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit(40, 60, "room_create"))],
)
async def create_room(
    payload: RoomCreateRequest,
    room_service: RoomService = Depends(get_room_service),
) -> RoomCreateResponse:
    room_id = await room_service.create_room(payload.config)
    room_status = await room_service.get_status(room_id)
    if room_status is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Room init failed")

    return RoomCreateResponse(room_id=room_id, status=room_status)


@router.get(
    "/{room_id}/join-check",
    response_model=RoomJoinCheckResponse,
    dependencies=[Depends(rate_limit(120, 60, "room_join_check"))],
)
async def join_check(
    room_id: str,
    room_service: RoomService = Depends(get_room_service),
) -> RoomJoinCheckResponse:
    room_status = await room_service.get_status(room_id)
    if room_status is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")

    return RoomJoinCheckResponse(
        room_id=room_id,
        can_join=(room_status.value == "LOBBY"),
        status=room_status,
    )


@router.post(
    "/{room_id}/transition",
    response_model=RoomStateResponse,
    dependencies=[Depends(rate_limit(80, 60, "room_transition"))],
)
async def transition_room(
    room_id: str,
    payload: RoomTransitionRequest,
    room_service: RoomService = Depends(get_room_service),
) -> RoomStateResponse:
    try:
        room_status = await room_service.transition_status(room_id, payload.status)
    except ValueError as exc:
        message = str(exc)
        if "not found" in message.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message) from exc

    timing = {"ends_at": 0, "test_ends_at": 0, "current_question": 0}
    if room_status == RoomStatus.ACTIVE:
        timing = await room_service.activate_session(room_id)

    engine = get_realtime_engine()
    await engine.broadcast(
        room_id,
        {
            "type": "ROOM_STATE_CHANGE",
            "status": room_status.value,
            "ends_at": timing["ends_at"],
            "test_ends_at": timing["test_ends_at"],
            "current_question": timing["current_question"],
        },
    )

    config = await room_service.get_config(room_id)
    if room_status == RoomStatus.ACTIVE and config.mode.value == "QUIZ":
        await engine.publish_current_question(room_id)
    if room_status == RoomStatus.ACTIVE and config.mode.value == "TEST":
        await engine.publish_test_sections(room_id)

    return RoomStateResponse(
        room_id=room_id,
        status=room_status,
        ends_at=timing["ends_at"],
        test_ends_at=timing["test_ends_at"],
        current_question=timing["current_question"],
    )


@router.post(
    "/{room_id}/generate-questions",
    response_model=RoomGenerationResponse,
    dependencies=[Depends(rate_limit(30, 60, "room_generate"))],
)
async def generate_questions(
    room_id: str,
    room_service: RoomService = Depends(get_room_service),
) -> RoomGenerationResponse:
    current_status = await room_service.get_status(room_id)
    if current_status is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")
    if current_status != RoomStatus.LOBBY:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Room must be in LOBBY")

    await room_service.transition_status(room_id, RoomStatus.GENERATING)
    config = await room_service.get_config(room_id)

    package = await quiz_generator.generate(config)
    await room_service.save_question_package(room_id, package)
    history_service.persist_quiz_history(room_id, config, package)

    active_status = await room_service.transition_status(room_id, RoomStatus.ACTIVE)
    timing = await room_service.activate_session(room_id)

    engine = get_realtime_engine()
    await engine.broadcast(
        room_id,
        {
            "type": "ROOM_STATE_CHANGE",
            "status": active_status.value,
            "ends_at": timing["ends_at"],
            "test_ends_at": timing["test_ends_at"],
            "current_question": timing["current_question"],
        },
    )

    if config.mode.value == "QUIZ":
        await engine.publish_current_question(room_id)
    if config.mode.value == "TEST":
        await engine.publish_test_sections(room_id)

    return RoomGenerationResponse(
        room_id=room_id,
        status=active_status,
        question_count=len(package.questions),
        ends_at=timing["ends_at"],
        test_ends_at=timing["test_ends_at"],
        current_question=timing["current_question"],
    )
