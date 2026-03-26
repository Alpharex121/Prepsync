# PrepSync v1 Release Notes

Release date: 2026-03-26

## Highlights

- Real-time multiplayer `quiz` mode with synchronized question flow.
- Real-time peer `test` mode with per-user pacing and section locking.
- Topic and exam-based room composition with section-wise progression.
- Session history and detailed reports for quiz/test attempts.
- Room analytics endpoints for admin monitoring.

## Included in v1

- Auth and role-aware room lifecycle APIs.
- WebSocket event flow for join/start/submit/results.
- Anti-cheat and validation for duplicate/late submissions.
- Rate limiting for auth and room actions.
- Structured logging and metrics hooks.
- Dockerfiles for backend and frontend services.
- CI/CD deploy workflow for tagged releases.
- SQL migration and seed script baseline.
- Production env templates and secrets strategy docs.
- Rollback and incident response checklist.

## Known limitations

- Deploy workflow includes migration/smoke placeholders that must be wired to target infra.
- Load test suite currently includes baseline health scenario; high-fidelity room simulation is pending.
- No blue-green or canary automation yet in CI pipeline.
- Monitoring integrations are hook-ready but not fully connected to a managed APM backend.
