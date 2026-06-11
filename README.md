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

- **Backend** — Python + FastAPI, run by Uvicorn on port 8001. Holds service status, exposes read endpoints and a webhook write endpoint, validates input with Pydantic, self-documents at `/docs`.
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
python -m uvicorn main:app --reload
```
Backend runs at http://localhost:8001 — interactive API docs at http://localhost:8001/docs

**Frontend:**
```
cd statuspulse/frontend
npm run dev
```
Frontend runs at http://localhost:3000

Create `statuspulse/frontend/.env.local` with:
```
NEXT_PUBLIC_API_URL=http://localhost:8001
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

---

## GitHub Workflow & Setup (For Personal Fork & Testing)

### Step 1: Fork the Repository (One-time)

Go to the original repository on GitHub and click the **Fork** button. This creates a copy under your personal account.

### Step 2: Clone Your Fork Locally

Open PowerShell and run:

```powershell
# Clone your forked repository
git clone https://github.com/YOUR_USERNAME/statuspulse.git
cd statuspulse

# Add the original repo as upstream (to sync updates later)
git remote add upstream https://github.com/ORIGINAL_OWNER/statuspulse.git

# Verify remotes
git remote -v
```

You should see:
- `origin` → your fork (push here)
- `upstream` → original repo (pull updates from here)

### Step 3: Complete Local Setup (Fresh Clone)

**In a new folder on your machine:**

```powershell
# Create and navigate to project folder
mkdir c:\projects\statuspulse
cd c:\projects\statuspulse

# Clone your fork
git clone https://github.com/YOUR_USERNAME/statuspulse.git .

# Open in VS Code
code .
```

**Install Dependencies & Run:**

Open **two PowerShell terminals** in VS Code (`Ctrl+Shift+` ` twice):

**Terminal 1 — Backend:**
```powershell
cd statuspulse/backend

# Create virtual environment (if not exists)
python -m venv venv

# Activate it
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Run backend
python -m uvicorn main:app --reload
```

Backend is now running at **http://localhost:8001** (docs at `/docs`)

**Terminal 2 — Frontend:**
```powershell
cd statuspulse/frontend

# Install dependencies
npm install

# Create .env.local
echo 'NEXT_PUBLIC_API_URL=http://localhost:8001' > .env.local

# Run frontend
npm run dev
```

Frontend is now running at **http://localhost:3000**

**Verify it works:**
- Open http://localhost:3000 in your browser
- You should see the StatusPulse dashboard
- Both terminals show no errors

---

### Step 4: Make Changes & Commit

```powershell
# Create a feature branch (don't commit to main)
git checkout -b feature/my-new-feature

# Make your changes in VS Code...

# Check what changed
git status

# Stage changes
git add .

# Commit with descriptive message
git commit -m "Add new feature: description here"

# Push to your fork
git push origin feature/my-new-feature
```

### Step 5: Create a Pull Request (PR)

1. Go to your fork on GitHub (`https://github.com/YOUR_USERNAME/statuspulse`)
2. You'll see a banner: "Compare & pull request" — click it
3. Write a description of your changes
4. Click "Create Pull Request"
5. Wait for feedback / GitHub Actions to run

### Step 6: Keep Your Fork Updated

```powershell
# Fetch latest from original repo
git fetch upstream

# Merge into your main branch
git checkout main
git merge upstream/main

# Push to your fork
git push origin main
```

### Step 7: Merge After Approval

Once PR is approved and tests pass:

1. On GitHub, click "Merge pull request"
2. Optionally delete the feature branch
3. Pull the merged changes locally:

```powershell
git checkout main
git pull origin main
```

---

## GitHub Actions Setup (CI/CD)

### Create `.github/workflows/ci.yml`

In your cloned repo, create:

```
.github/workflows/ci.yml
```

**Content:**

```yaml
name: CI/CD Pipeline

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: 3.11
      
      - name: Install backend dependencies
        run: |
          cd statuspulse/backend
          pip install -r requirements.txt
      
      - name: Set up Node.js
        uses: actions/setup-node@v4
        with:
          node-version: 20
      
      - name: Install frontend dependencies
        run: |
          cd statuspulse/frontend
          npm install
      
      - name: Lint frontend
        run: |
          cd statuspulse/frontend
          npm run lint
      
      - name: Build frontend
        run: |
          cd statuspulse/frontend
          npm run build
      
      - name: Run backend tests (when added)
        run: |
          cd statuspulse/backend
          echo "Tests will run here when pytest tests are added"
```

Push this file:

```powershell
git add .github/workflows/ci.yml
git commit -m "Add CI/CD workflow"
git push origin feature/add-github-actions
```

Now every push/PR triggers automated tests.

---

## AWS Integration Path

### Phase 1: Containerization
```dockerfile
# statuspulse/backend/Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0"]
```

```dockerfile
# statuspulse/frontend/Dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json .
RUN npm install
COPY . .
RUN npm run build

FROM node:20-alpine
WORKDIR /app
COPY --from=build /app/.next ./.next
COPY package*.json .
RUN npm install --production
CMD ["npm", "start"]
```

### Phase 2: Push to AWS ECR (in GitHub Actions)
```yaml
- name: Push to AWS ECR
  run: |
    aws ecr get-login-password --region ${{ secrets.AWS_REGION }} | docker login --username AWS --password-stdin ${{ secrets.AWS_ACCOUNT_ID }}.dkr.ecr.${{ secrets.AWS_REGION }}.amazonaws.com
    docker build -t backend statuspulse/backend
    docker tag backend:latest ${{ secrets.AWS_ACCOUNT_ID }}.dkr.ecr.${{ secrets.AWS_REGION }}.amazonaws.com/backend:latest
    docker push ${{ secrets.AWS_ACCOUNT_ID }}.dkr.ecr.${{ secrets.AWS_REGION }}.amazonaws.com/backend:latest
```

### Phase 3: Deploy to ECS/Fargate
- Use CloudFormation or Terraform for IaC
- Deploy frontend to S3 + CloudFront
- Backend to ECS/Fargate behind ALB
- Database: RDS Postgres

---

## Quick Reference: Git Commands

| Command | Purpose |
|---------|---------|
| `git clone <url>` | Clone repo |
| `git checkout -b <branch>` | Create & switch to branch |
| `git add .` | Stage all changes |
| `git commit -m "msg"` | Commit with message |
| `git push origin <branch>` | Push to your fork |
| `git pull origin main` | Pull latest from main |
| `git fetch upstream` | Fetch from original repo |
| `git merge upstream/main` | Merge original's main |
| `git status` | See what changed |
| `git log --oneline` | View commit history |

---

## Summary: Your Development Workflow

1. **Fork** → Clone → Create branch
2. **Develop** → Commit → Push to your fork
3. **PR** → GitHub Actions runs tests
4. **Review** → Merge when approved
5. **Deploy** → GitHub Actions pushes to AWS (ECR → ECS/Fargate)

Ready to test GitHub Actions and AWS integration!
#   t e s t  
 