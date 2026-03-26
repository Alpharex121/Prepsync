# PrepSync Backend

## Local setup

1. Create and activate a Python 3.11+ virtual environment.
2. Install dependencies:
   `pip install -r requirements.txt -r requirements-dev.txt`
3. Start server from `backend/`:
   `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`

## Security & reliability

- Rate limits on auth and room actions (`429` on bursts).
- WebSocket payloads validated with Pydantic schemas.
- Anti-cheat checks include duplicate-answer rejection and late-submit windows.

## Observability hooks

- Structured request logging middleware.
- Error logging helper and simple in-memory metric counters.
- Hook points live in `app/core/observability.py`.

## Tests added

- Unit: room state machine (`tests/test_room_state_machine.py`)
- Integration: websocket event validation/join (`tests/test_websocket_integration.py`)
- E2E: quiz/test backend flows (`tests/test_e2e_modes.py`)

## Quality checks

- `ruff check .`
- `ruff format --check .`
- `pytest`
