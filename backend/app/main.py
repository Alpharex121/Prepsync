from pydantic import ValidationError
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.history import router as history_router
from app.api.room import router as room_router
from app.core.config import settings
from app.core.observability import elapsed_ms, log_error, log_request, timed
from app.middleware.late_join_guard import LateJoinGuardMiddleware
from app.schemas.ws import (
    JoinRoomEvent,
    NavigateQuestionEvent,
    RoomStateChangeEvent,
    SubmitAnswerEvent,
    SubmitSectionEvent,
)
from app.services.realtime import get_realtime_engine

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(LateJoinGuardMiddleware)

app.include_router(auth_router)
app.include_router(room_router)
app.include_router(history_router)


async def _safe_send_json(websocket: WebSocket, payload: dict) -> bool:
    try:
        await websocket.send_json(payload)
        return True
    except (RuntimeError, WebSocketDisconnect):
        return False


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start = timed()
    try:
        response = await call_next(request)
    except Exception as exc:
        log_error("http_request", exc)
        raise
    log_request(request.method, request.url.path, response.status_code, elapsed_ms(start))
    return response


@app.on_event("startup")
async def startup_event() -> None:
    await get_realtime_engine().start()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await get_realtime_engine().stop()


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


@app.websocket("/ws/rooms/{room_id}")
async def room_socket(websocket: WebSocket, room_id: str) -> None:
    await websocket.accept()

    engine = get_realtime_engine()
    user_id = websocket.query_params.get("user_id")

    if user_id and engine.has_session(room_id, user_id):
        await engine.connect(room_id, user_id, websocket)
        if not await _safe_send_json(websocket, {"type": "RECONNECTED", "room_id": room_id, "user_id": user_id}):
            return
    else:
        if not await _safe_send_json(websocket, {"type": "CONNECTED", "room_id": room_id}):
            return

    try:
        while True:
            payload = await websocket.receive_json()
            event_type = payload.get("type")

            if event_type == "JOIN_ROOM":
                try:
                    event = JoinRoomEvent.model_validate(payload)
                except ValidationError as exc:
                    await _safe_send_json(websocket, {"type": "ERROR", "detail": f"Invalid JOIN_ROOM payload: {exc}"})
                    continue

                user_id = event.user_id
                await engine.connect(room_id, user_id, websocket)
                await engine.touch(room_id, user_id)
                ack = await engine.handle_join_room(room_id, user_id)
                if not await _safe_send_json(websocket, ack):
                    await engine.disconnect(room_id, user_id)
                    return
                await engine.broadcast(
                    room_id,
                    {
                        "type": "USER_JOINED",
                        "room_id": room_id,
                        "user_id": user_id,
                        "participants": engine.get_participants(room_id),
                    },
                )
                continue

            if not user_id:
                await _safe_send_json(websocket, {"type": "ERROR", "detail": "JOIN_ROOM is required before this event"})
                continue

            await engine.touch(room_id, user_id)

            if event_type == "ROOM_STATE_CHANGE":
                try:
                    event = RoomStateChangeEvent.model_validate(payload)
                    ws_event = await engine.handle_room_state_change(room_id, user_id, event.status)
                except (ValidationError, ValueError) as exc:
                    await _safe_send_json(websocket, {"type": "ERROR", "detail": str(exc)})
                else:
                    await _safe_send_json(websocket, ws_event)
                continue

            if event_type == "SUBMIT_ANSWER":
                try:
                    event = SubmitAnswerEvent.model_validate(payload)
                except ValidationError as exc:
                    await _safe_send_json(websocket, {"type": "ERROR", "detail": f"Invalid SUBMIT_ANSWER payload: {exc}"})
                    continue

                ws_event = await engine.handle_submit_answer(
                    room_id,
                    user_id,
                    question_index=event.question_index,
                    selected_option=event.selected_option,
                )
                await _safe_send_json(websocket, ws_event)
                continue

            if event_type == "NAVIGATE_QUESTION":
                try:
                    event = NavigateQuestionEvent.model_validate(payload)
                except ValidationError as exc:
                    await _safe_send_json(websocket, {"type": "ERROR", "detail": f"Invalid NAVIGATE_QUESTION payload: {exc}"})
                    continue

                ws_event = await engine.handle_navigate_question(room_id, user_id, event.question_index)
                await _safe_send_json(websocket, ws_event)
                continue

            if event_type == "SUBMIT_SECTION":
                try:
                    event = SubmitSectionEvent.model_validate(payload)
                except ValidationError as exc:
                    await _safe_send_json(websocket, {"type": "ERROR", "detail": f"Invalid SUBMIT_SECTION payload: {exc}"})
                    continue

                ws_event = await engine.handle_submit_section(room_id, user_id, event.section_index)
                await _safe_send_json(websocket, ws_event)
                continue

            if event_type == "FINAL_RESULTS":
                ws_event = await engine.finalize_results(room_id)
                await _safe_send_json(websocket, ws_event)
                continue

            await _safe_send_json(websocket, {"type": "ERROR", "detail": f"Unknown event: {event_type}"})

    except WebSocketDisconnect:
        if user_id:
            await engine.disconnect(room_id, user_id)
            await engine.maybe_advance_quiz_on_presence_change(room_id)
            await engine.broadcast(
                room_id,
                {
                    "type": "USER_LEFT",
                    "room_id": room_id,
                    "user_id": user_id,
                    "participants": engine.get_participants(room_id),
                },
            )
        return
    except Exception as exc:
        log_error("websocket_room", exc)
        raise


