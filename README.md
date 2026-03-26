# PrepSync

Real-time competitive quiz and test platform.

## Monorepo layout

- `backend/`: FastAPI service
- `frontend/`: React + Vite app
- `shared/`: shared contracts/schemas
- `design/`: architecture and phase documents

## Implemented scope (through Phase 11)

- Authentication and room lifecycle APIs
- Real-time quiz and test mode orchestration
- Section-wise test progression and submission locking
- Attempt history, reports, and analytics endpoints
- Validation, anti-cheat, rate limiting, and observability hooks
- Unit, integration, and e2e backend test coverage for core flows
- Dockerized backend/frontend builds and tagged deploy workflow
- Production env templates, migration/seed SQL, and release runbooks

## Production and release docs

- `/.env.production.example`
- `/backend/.env.production.example`
- `/backend/migrations/001_initial.sql`
- `/backend/scripts/seed.sql`
- `/backend/loadtest/README.md`
- `/design/release/secrets_strategy.md`
- `/design/release/rollback_incident.md`
- `/design/release/v1_release_notes.md`
