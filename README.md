# test-application
# StatusPulse

A learning project that builds a **service status platform** end to end — the same architecture as an enterprise status page (e.g. monitoring tools → backend → dashboard), built to *understand* how the pieces connect, not just to ship a website.

## What it is

StatusPulse answers one question for a whole organization: **"is service X up, degraded, or down right now?"** — automatically, with minimal manual updates. Monitoring tools report status via a webhook; the backend holds it; a live dashboard displays it.

## Architecture (current)

```
monitoring tool ──POST /webhook/status──▶  FastAPI backend  ──GET /services──▶  Next.js dashboard
   (simulated)                            (in-memory store)                    (live, auto-refresh)
```

- **Backend** — Python + FastAPI, run by Uvicorn on port 8000. Holds service status, exposes read endpoints and a webhook write endpoint, validates input with Pydantic, self-documents at `/docs`.
- **Frontend** — Next.js (TypeScript + Tailwind) on port 3000. Fetches `/services`, renders colored status cards, auto-refreshes every 10s, handles loading and error states, reads the backend URL from an env var.

## Tech stack

| Layer | Technology | Maps to (production / AWS) |
|---|---|---|
| Frontend | Next.js, TypeScript, Tailwind | ECS/Fargate or S3+CloudFront |
| Backend API | Python, FastAPI, Uvicorn | ECS/Fargate behind an ALB |
| Data store | in-memory dict (today) | RDS/Aurora Postgres + ElastiCache Redis |
| Message bus | (planned) | SNS + SQS |
| CI/CD | (planned) | GitHub Actions |
| Containers | (planned) | Docker images in ECR |

## Running locally

Two servers, two terminals.

**Backend:**
```
cd statuspulse/backend
.\venv\Scripts\Activate.ps1      # Windows  (Mac/Linux: source venv/bin/activate)
python -m uvicorn main:app --reload   (if main is directly in the backend, else if its in app: python -m uvicorn app.main:app --reload 
```
Backend runs at http://localhost:8000 — interactive API docs at http://localhost:8000/docs

**Frontend:**
```
cd statuspulse/frontend
npm run dev
```
Frontend runs at http://localhost:3000

Create `statuspulse/frontend/.env.local` with:
```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## Concepts demonstrated

- REST API design (GET/POST, status codes, JSON), webhooks, input validation
- Frontend ↔ backend wiring, CORS, fetch, React state
- Loading / error / data state handling, auto-refresh with interval cleanup
- Config via environment variables (not hardcoded URLs)

## Roadmap

- Real persistence (Postgres) + history of status events
- Caching layer (Redis, cache-aside pattern)
- Decoupled ingestion (message bus / async queue)
- Containerization (Docker) and CI/CD (GitHub Actions)
- AWS deployment mapping (ECS, RDS, ElastiCache, ALB, CloudWatch)
