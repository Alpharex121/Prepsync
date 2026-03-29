from datetime import UTC, datetime

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
from app.services.room_generation_logger import room_generation_logger
from app.services.room import RoomService, get_room_service

router = APIRouter(prefix="/rooms", tags=["rooms"])
@router.get(
    "/current",
    dependencies=[Depends(rate_limit(120, 60, "room_current"))],
)
async def current_room(
    user_id: str,
    room_service: RoomService = Depends(get_room_service),
) -> dict:
    engine = get_realtime_engine()
    get_user_rooms = getattr(engine, "get_user_rooms", None)
    candidate_rooms = get_user_rooms(user_id) if callable(get_user_rooms) else []

    active_choice: str | None = None
    generating_choice: str | None = None
    for candidate in candidate_rooms:
        room_status = await room_service.get_status(candidate)
        if room_status is None:
            continue
        if room_status == RoomStatus.ACTIVE:
            active_choice = candidate
            break
        if room_status == RoomStatus.GENERATING:
            generating_choice = candidate

    selected = active_choice or generating_choice
    if not selected:
        return {"has_ongoing": False, "room_id": None, "status": None}

    selected_status = await room_service.get_status(selected)
    return {
        "has_ongoing": True,
        "room_id": selected,
        "status": selected_status.value if selected_status else None,
    }


@router.post(
    "/create",
    response_model=RoomCreateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit(40, 60, "room_create"))],
)
async def create_room(
    payload: RoomCreateRequest,
    user_id: str,
    room_service: RoomService = Depends(get_room_service),
) -> RoomCreateResponse:
    room_id = await room_service.create_room(payload.config.model_copy(update={"owner_id": user_id}))
    room_status = await room_service.get_status(room_id)
    if room_status is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Room init failed")

    room_generation_logger.write_json(
        room_id,
        "00_room_create_input.json",
        {
            "created_at": datetime.now(UTC).isoformat(),
            "user_id": user_id,
            "payload": payload.model_dump(mode="json"),
        },
    )
    room_generation_logger.write_json(
        room_id,
        "01_room_create_response.json",
        {
            "created_at": datetime.now(UTC).isoformat(),
            "room_id": room_id,
            "status": room_status.value,
        },
    )

    return RoomCreateResponse(room_id=room_id, status=room_status)


@router.get(
    "/{room_id}/join-check",
    response_model=RoomJoinCheckResponse,
    dependencies=[Depends(rate_limit(120, 60, "room_join_check"))],
)
async def join_check(
    room_id: str,
    user_id: str | None = None,
    room_service: RoomService = Depends(get_room_service),
) -> RoomJoinCheckResponse:
    room_status = await room_service.get_status(room_id)
    if room_status is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")

    can_join = room_status.value == "LOBBY"
    if not can_join and user_id:
        engine = get_realtime_engine()
        can_join = engine.has_session(room_id, user_id)

    return RoomJoinCheckResponse(
        room_id=room_id,
        can_join=can_join,
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
    user_id: str,
    room_service: RoomService = Depends(get_room_service),
) -> RoomStateResponse:
    try:
        owner_id = await room_service.get_owner_id(room_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if owner_id and owner_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only room admin can start or transition")

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
    user_id: str,
    room_service: RoomService = Depends(get_room_service),
) -> RoomGenerationResponse:
    try:
        owner_id = await room_service.get_owner_id(room_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if owner_id and owner_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only room admin can start the session")

    current_status = await room_service.get_status(room_id)
    if current_status is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")
    if current_status != RoomStatus.LOBBY:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Room must be in LOBBY")

    generating_status = await room_service.transition_status(room_id, RoomStatus.GENERATING)
    engine = get_realtime_engine()
    await engine.broadcast(
        room_id,
        {
            "type": "ROOM_STATE_CHANGE",
            "status": generating_status.value,
            "ends_at": 0,
            "test_ends_at": 0,
            "current_question": 0,
        },
    )

    config = await room_service.get_config(room_id)
    room_generation_logger.write_json(
        room_id,
        "10_generation_input.json",
        {
            "started_at": datetime.now(UTC).isoformat(),
            "room_id": room_id,
            "user_id": user_id,
            "config": config.model_dump(mode="json"),
            "generating_event": {
                "type": "ROOM_STATE_CHANGE",
                "status": generating_status.value,
                "ends_at": 0,
                "test_ends_at": 0,
                "current_question": 0,
            },
        },
    )

    package, trace = await quiz_generator.generate_with_trace(config)

    room_generation_logger.write_json(room_id, "20_search_queries.json", trace.get("search", {}).get("queries", []))
    room_generation_logger.write_json(room_id, "21_search_results.json", trace.get("search", {}).get("results", []))
    room_generation_logger.write_text(room_id, "30_prompt_initial.txt", str(trace.get("prompt_initial", "")))
    room_generation_logger.write_json(
        room_id,
        "31_llm_attempts.json",
        trace.get("attempts", []),
    )
    room_generation_logger.write_json(
        room_id,
        "32_verification_summary.json",
        {
            "provider": trace.get("provider"),
            "model": trace.get("model"),
            "mode": trace.get("mode"),
            "reference_count": trace.get("reference_count"),
            "expected_total": trace.get("expected_total"),
            "fallback_used": trace.get("fallback_used"),
            "fallback_reason": trace.get("fallback_reason"),
        },
    )

    await room_service.save_question_package(room_id, package)
    history_service.persist_quiz_history(room_id, config, package)

    room_generation_logger.write_json(
        room_id,
        "40_final_package.json",
        package.model_dump(mode="json"),
    )

    active_status = await room_service.transition_status(room_id, RoomStatus.ACTIVE)
    timing = await room_service.activate_session(room_id)

    active_event = {
        "type": "ROOM_STATE_CHANGE",
        "status": active_status.value,
        "ends_at": timing["ends_at"],
        "test_ends_at": timing["test_ends_at"],
        "current_question": timing["current_question"],
    }
    await engine.broadcast(room_id, active_event)

    front_payload = {
        "room_id": room_id,
        "status": active_status.value,
        "question_count": len(package.questions),
        "ends_at": timing["ends_at"],
        "test_ends_at": timing["test_ends_at"],
        "current_question": timing["current_question"],
    }

    room_generation_logger.write_json(room_id, "50_active_event.json", active_event)
    room_generation_logger.write_json(room_id, "60_frontend_response.json", front_payload)

    if config.mode.value == "QUIZ":
        next_question_event = await engine.publish_current_question(room_id)
        room_generation_logger.write_json(room_id, "70_initial_quiz_event.json", next_question_event)
    if config.mode.value == "TEST":
        await engine.publish_test_sections(room_id)
        room_generation_logger.write_json(
            room_id,
            "70_initial_test_event.json",
            {"type": "TEST_SECTION_START", "detail": "Published section payload to participants"},
        )

    return RoomGenerationResponse(
        room_id=room_id,
        status=active_status,
        question_count=len(package.questions),
        ends_at=timing["ends_at"],
        test_ends_at=timing["test_ends_at"],
        current_question=timing["current_question"],
    )






