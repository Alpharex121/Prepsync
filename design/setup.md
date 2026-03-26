# PrepSync Setup Guide

Last updated: 2026-03-26

## 1) Complete `.env` Setup

## 1.1 Backend env (`backend/.env`)
Create `backend/.env` with:

```env
APP_ENV=development
APP_NAME=PrepSync
API_HOST=0.0.0.0
API_PORT=8000
CORS_ALLOW_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

JWT_SECRET_KEY=replace-me-in-production
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60

# LLM provider options: openai | gemini | groq
LLM_PROVIDER=openai
# Model examples by provider:
# openai: gpt-4o-mini, gpt-4.1-mini, gpt-4.1
# gemini: gemini-1.5-flash, gemini-1.5-pro
# groq: llama-3.1-8b-instant, llama-3.3-70b-versatile
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=
GEMINI_API_KEY=
GROQ_API_KEY=

POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=prepsync
POSTGRES_USER=prepsync
POSTGRES_PASSWORD=prepsync

REDIS_HOST=localhost
REDIS_PORT=6379
```

How to get each backend value:
- `APP_*`, `API_*`: keep default unless you need custom host/port.
- `JWT_SECRET_KEY`: generate a strong random secret.
  - PowerShell example:
    ```powershell
    [Convert]::ToBase64String((1..64 | ForEach-Object { Get-Random -Minimum 0 -Maximum 256 }))
    ```
- `LLM_PROVIDER`: choose one of `openai`, `gemini`, `groq`.
- `LLM_MODEL`: pick a model valid for the selected provider.
- `LLM_API_KEY`: required when `LLM_PROVIDER=openai`.
- `GEMINI_API_KEY`: required when `LLM_PROVIDER=gemini`.
- `GROQ_API_KEY`: required when `LLM_PROVIDER=groq`.
- `POSTGRES_*` local: use docker-compose defaults in this repo.
- `REDIS_*` local: use docker-compose defaults in this repo.

Provider key links:
- OpenAI: https://platform.openai.com/api-keys
- Gemini (Google AI Studio): https://aistudio.google.com/app/apikey
- Groq: https://console.groq.com/keys

## 1.2 Frontend env (`frontend/.env.local`)
Create `frontend/.env.local` with:

```env
VITE_API_BASE_URL=http://localhost:8000
```

How to get frontend value:
- `VITE_API_BASE_URL`: backend public base URL (local: `http://localhost:8000`, production: your backend HTTPS URL).

## 1.3 Production backend env (`backend/.env.production`)
For hosted backend, use:

```env
APP_ENV=production
APP_NAME=PrepSync
API_HOST=0.0.0.0
API_PORT=8000
CORS_ALLOW_ORIGINS=https://<your-project>.vercel.app

JWT_SECRET_KEY=<strong-secret>
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60

# LLM provider options: openai | gemini | groq
LLM_PROVIDER=openai
# openai: gpt-4o-mini, gpt-4.1-mini, gpt-4.1
# gemini: gemini-1.5-flash, gemini-1.5-pro
# groq: llama-3.1-8b-instant, llama-3.3-70b-versatile
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=<set-if-provider-is-openai>
GEMINI_API_KEY=<set-if-provider-is-gemini>
GROQ_API_KEY=<set-if-provider-is-groq>

POSTGRES_HOST=<managed-postgres-host>
POSTGRES_PORT=5432
POSTGRES_DB=<managed-postgres-db>
POSTGRES_USER=<managed-postgres-user>
POSTGRES_PASSWORD=<managed-postgres-password>

REDIS_HOST=<managed-redis-host>
REDIS_PORT=6379
```

Important for this codebase:
- Redis config currently supports only host+port (no password field), so use an internal/private Redis endpoint that does not require auth, or extend backend settings to support Redis auth.

## 2) Local Development Setup (Complete)

Prerequisites:
- Python 3.11+
- Node.js 20+
- Docker + Docker Compose

## 2.1 Start local Postgres + Redis
From repo root:

```powershell
docker compose up -d
```

## 2.2 Backend setup

```powershell
cd backend
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Optional DB initialization:

```powershell
psql "postgresql://prepsync:prepsync@localhost:5432/prepsync" -f migrations/001_initial.sql
psql "postgresql://prepsync:prepsync@localhost:5432/prepsync" -f scripts/seed.sql
```

## 2.3 Frontend setup
Open a second terminal:

```powershell
cd frontend
Set-Content .env.local "VITE_API_BASE_URL=http://localhost:8000"
npm install
npm run dev
```

Frontend runs at `http://localhost:5173`.

## 2.4 Quick verification
- Backend health: `http://localhost:8000/health`
- Frontend: open `http://localhost:5173`
- Create account -> create room -> start session.

## 3) Hosting on Free Services (Complete Path)

Recommended free stack:
- Frontend: Vercel (free)
- Backend: Render Web Service (free)
- Postgres: Render Postgres (free)
- Redis: Render Key Value (free)

Note (as of 2026-03-26): Render free services have limitations (spin-down, monthly limits, free Postgres 30-day expiry, free key-value in-memory behavior). See sources below.

## 3.1 Deploy backend to Render (free)
1. Push repo to GitHub.
2. Render Dashboard -> New -> Web Service.
3. Connect GitHub repo.
4. Choose runtime: Docker.
5. Set Dockerfile path: `backend/Dockerfile`.
6. Set root directory to repo root.
7. Add backend env vars (from section 1.3).
8. Set health check path: `/health`.
9. Deploy.

## 3.2 Create free Postgres + Redis on Render
1. Render Dashboard -> New -> Postgres -> choose Free.
2. Render Dashboard -> New -> Key Value -> choose Free.
3. Keep all in same Render region/workspace as backend.
4. From Postgres dashboard, collect host/db/user/password/port.
5. From Key Value dashboard, copy internal URL and extract:
- `REDIS_HOST` = host from `redis://host:port`
- `REDIS_PORT` = port from that URL

## 3.3 Wire backend env to Render data stores
Update backend env vars in Render service:
- `POSTGRES_HOST`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_PORT`
- `REDIS_HOST`, `REDIS_PORT`
Then redeploy backend.

## 3.4 Deploy frontend to Vercel (free)
1. Vercel -> Add New Project -> import same repo.
2. Set root directory to `frontend`.
3. Framework: Vite (auto-detected).
4. Build command: `npm run build`.
5. Output directory: `dist`.
6. Add env var:
   - `VITE_API_BASE_URL=https://<your-backend>.onrender.com`
7. Deploy.

## 3.5 CORS setup via env
Set backend env var on Render:
- CORS_ALLOW_ORIGINS=https://<your-project>.vercel.app
- For multiple origins, use comma-separated values.

Redeploy backend after env update.

## 3.6 Production sanity checklist
- Backend `/health` returns `ok`.
- Frontend can register/login.
- Room create/join works.
- WebSocket connects and receives `JOIN_ROOM_ACK`.
- Quiz/Test flow completes and history/report loads.

## Sources
- Render free instances and limits: https://render.com/docs/free
- Render Docker deploys: https://render.com/docs/docker
- Render Key Value connection behavior: https://render.com/docs/key-value
- Vite on Vercel: https://vercel.com/docs/frameworks/frontend/vite
- Vercel environment variables: https://vercel.com/docs/environment-variables
- OpenAI API keys: https://platform.openai.com/api-keys
- Google AI Studio API keys: https://aistudio.google.com/app/apikey
- Groq API keys: https://console.groq.com/keys
