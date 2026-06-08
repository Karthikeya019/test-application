from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone
from enum import Enum

import asyncio
import httpx
import json
import os
import time

import redis

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_serializer
from sqlalchemy import Column, DateTime, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


# ---------------------------------------------------------------------------
# Database setup
# engine writes to a local SQLite file; check_same_thread=False is required
# because FastAPI may call from threads other than the one that created it
# ---------------------------------------------------------------------------
DATABASE_URL = "sqlite:///./statuspulse.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# SessionLocal is a factory; call it to get a Session object
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Two-table design:
#   services       — current state, one row per service (mutable, upserted)
#   status_checks  — append-only history, one row per health-check or webhook
# ---------------------------------------------------------------------------
class ServiceRow(Base):
    __tablename__ = "services"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    status = Column(String, nullable=False)
    last_updated = Column(DateTime(timezone=True), nullable=False)
    check_url = Column(String, nullable=True)
    detail = Column(String, nullable=True)


class StatusCheck(Base):
    __tablename__ = "status_checks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    service_id = Column(String, index=True, nullable=False)
    status = Column(String, nullable=False)
    response_ms = Column(Integer, nullable=True)   # null when no HTTP response received
    detail = Column(String, nullable=True)
    checked_at = Column(DateTime(timezone=True), nullable=False, index=True)


# ---------------------------------------------------------------------------
# Session helper — always closes the session, even on exception
# ---------------------------------------------------------------------------
@contextmanager
def get_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Redis setup — read host/port from env so dev and prod can differ
# decode_responses=True means get() returns str, not bytes
# ---------------------------------------------------------------------------
CACHE_KEY_SERVICES = "services:all"
CACHE_TTL = 10  # seconds — safety net in case invalidation is ever missed

redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    decode_responses=True,
)


def cache_get(key: str) -> str | None:
    """Return cached value or None. Logs a warning and returns None if Redis is down."""
    try:
        return redis_client.get(key)
    except redis.RedisError as exc:
        print(f"[cache] WARNING: Redis unavailable ({exc}), falling back to DB")
        return None


def cache_set(key: str, value: str, ex: int) -> None:
    """Set a cache key with TTL. Silently skips if Redis is down."""
    try:
        redis_client.set(key, value, ex=ex)
    except redis.RedisError as exc:
        print(f"[cache] WARNING: Redis unavailable ({exc}), skipping cache set")


def cache_delete(key: str) -> None:
    """Delete a cache key. Silently skips if Redis is down."""
    try:
        redis_client.delete(key)
        print(f"CACHE INVALIDATED: {key}")
    except redis.RedisError as exc:
        print(f"[cache] WARNING: Redis unavailable ({exc}), skipping cache invalidation")


def cache_incr(key: str) -> None:
    """Increment a Redis counter. Silently skips if Redis is down."""
    try:
        redis_client.incr(key)
    except redis.RedisError:
        pass


# ---------------------------------------------------------------------------
# Seed data — only written when the services table is empty at startup
# ---------------------------------------------------------------------------
SEED_SERVICES = [
    dict(id="jira",        name="Jira",         status="operational", check_url=None),
    dict(id="email",       name="Email",        status="degraded",    check_url=None),
    dict(id="google",      name="Google",       status="operational", check_url="https://www.google.com"),
    dict(id="github",      name="GitHub",       status="operational", check_url="https://www.github.com"),
    dict(id="outage-demo", name="Outage Demo",  status="operational", check_url="https://httpstat.us/503"),
]


def seed_if_empty():
    with get_session() as session:
        if session.query(ServiceRow).count() == 0:
            now = datetime.now(timezone.utc)
            for row in SEED_SERVICES:
                session.add(ServiceRow(**row, last_updated=now))


# ---------------------------------------------------------------------------
# Pydantic response models (kept separate from SQLAlchemy ORM models)
# ---------------------------------------------------------------------------
class StatusEnum(str, Enum):
    operational = "operational"
    degraded = "degraded"
    down = "down"


class Service(BaseModel):
    id: str
    name: str
    status: StatusEnum
    last_updated: datetime
    check_url: str | None = None
    detail: str | None = None

    model_config = {"from_attributes": True}

    @field_serializer("last_updated")
    def serialize_last_updated(self, v: datetime) -> str:
        # SQLite drops tz info; re-attach UTC before serializing so the
        # frontend always receives an unambiguous ISO 8601 timestamp
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.isoformat()


class UptimeResponse(BaseModel):
    service_id: str
    hours: int
    total_checks: int
    operational_checks: int
    uptime_percent: float


class CheckEntry(BaseModel):
    status: str
    response_ms: int | None
    detail: str | None
    checked_at: str  # ISO 8601 with UTC marker


class HistoryResponse(BaseModel):
    service_id: str
    count: int
    avg_response_ms: int | None
    latest_response_ms: int | None
    checks: list[CheckEntry]


class CacheStatsResponse(BaseModel):
    hits: int
    misses: int
    total: int
    hit_rate_percent: float


# ---------------------------------------------------------------------------
# Health-checker
# ---------------------------------------------------------------------------
async def check_service(client: httpx.AsyncClient, service_id: str, check_url: str) -> None:
    """Poll one service URL, then write updated state + history row to DB."""
    start = time.monotonic()
    status: str
    detail: str
    response_ms: int | None = None

    try:
        response = await client.get(check_url, timeout=5.0)
        response_ms = int((time.monotonic() - start) * 1000)

        # status-mapping: 2xx healthy unless slow; anything else is an error
        if response.is_success:
            if response_ms < 2500:
                status = "operational"
                detail = f"HTTP {response.status_code}, {response_ms}ms"
            else:
                status = "degraded"
                detail = f"Slow response: {response_ms}ms (server may be busy)"
        else:
            status = "degraded"
            detail = f"HTTP {response.status_code} — server error"

    except httpx.TimeoutException as exc:
        status = "down"
        detail = f"Timed out after 5s ({type(exc).__name__})"
    except httpx.ConnectError as exc:
        status = "down"
        detail = f"Connection failed: {type(exc).__name__}: {str(exc)[:80]}"
    except httpx.RequestError as exc:
        status = "down"
        detail = f"{type(exc).__name__}: {str(exc)[:100]}"

    now = datetime.now(timezone.utc)
    with get_session() as session:
        # (a) update current-state row
        row = session.get(ServiceRow, service_id)
        if row:
            row.status = status
            row.detail = detail
            row.last_updated = now
        # (b) append history row
        session.add(StatusCheck(
            service_id=service_id,
            status=status,
            response_ms=response_ms,
            detail=detail,
            checked_at=now,
        ))

    # invalidation is the primary freshness mechanism; TTL is a safety net
    cache_delete(CACHE_KEY_SERVICES)


async def health_check_loop() -> None:
    """Run forever: check every auto-monitored service every 30 seconds."""
    # LOCAL-DEV-ONLY workaround for Lilly's TLS-inspection proxy, which presents a
    # corporate CA that httpx doesn't trust by default. Set HEALTHCHECK_VERIFY_SSL=false
    # in .env only when running locally behind that proxy.
    # NEVER disable this in production — instead point httpx at the corporate CA bundle
    # via verify='path/to/ca.pem' or set the SSL_CERT_FILE env var system-wide.
    verify_ssl: bool = os.getenv("HEALTHCHECK_VERIFY_SSL", "true").lower() != "false"
    async with httpx.AsyncClient(follow_redirects=True, verify=verify_ssl) as client:
        while True:
            # extract plain (id, check_url) tuples while the session is open;
            # never pass ORM objects out of a closed session or asyncio tasks
            # will hit DetachedInstanceError when accessing their attributes
            with get_session() as session:
                targets = [
                    (svc.id, svc.check_url)
                    for svc in session.query(ServiceRow).filter(ServiceRow.check_url.isnot(None)).all()
                ]

            async def run(service_id: str, check_url: str) -> None:
                try:
                    await check_service(client, service_id, check_url)
                except Exception as exc:
                    print(f"[health-checker] {service_id}: {type(exc).__name__}: {exc}")

            await asyncio.gather(*[run(sid, url) for sid, url in targets])
            await asyncio.sleep(30)


# ---------------------------------------------------------------------------
# Lifespan: create tables, seed, then start background checker
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # create tables if they don't exist yet, then seed initial rows
    Base.metadata.create_all(bind=engine)
    seed_if_empty()

    # migrate existing DBs: update github's check_url if it still points at the API
    # (which returns 403 rate-limit errors and makes the service look degraded)
    with get_session() as session:
        gh = session.get(ServiceRow, "github")
        if gh and gh.check_url == "https://api.github.com":
            gh.check_url = "https://www.github.com"

    # start the background health-checker as a concurrent async task
    task = asyncio.create_task(health_check_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="StatusPulse API", lifespan=lifespan)

# CORS: browser blocks cross-origin requests unless we explicitly allow the frontend origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://172.29.192.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/services", response_model=list[Service])
def list_services():
    # cache-aside: check Redis first; on a miss, load from DB and populate cache.
    # Invalidation (DELETE after writes) is the primary freshness mechanism.
    # The TTL is a safety net only — it catches any write path that forgets to invalidate.
    cached = cache_get(CACHE_KEY_SERVICES)
    if cached is not None:
        print(f"CACHE HIT: {CACHE_KEY_SERVICES}")
        cache_incr("cache:hits")
        return json.loads(cached)

    print(f"CACHE MISS: {CACHE_KEY_SERVICES} — fetched from DB")
    cache_incr("cache:misses")
    with get_session() as session:
        rows = session.query(ServiceRow).all()
        services = [Service.model_validate(r) for r in rows]

    serialized = json.dumps([s.model_dump(mode="json") for s in services])
    cache_set(CACHE_KEY_SERVICES, serialized, ex=CACHE_TTL)
    return services


@app.get("/services/{service_id}", response_model=Service)
def get_service(service_id: str):
    with get_session() as session:
        row = session.get(ServiceRow, service_id)
        if not row:
            raise HTTPException(status_code=404, detail="Service not found")
        return Service.model_validate(row)


@app.get("/services/{service_id}/uptime", response_model=UptimeResponse)
def get_uptime(service_id: str, hours: int = 24):
    with get_session() as session:
        if not session.get(ServiceRow, service_id):
            raise HTTPException(status_code=404, detail="Service not found")

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        # uptime = operational checks / total checks over the window
        total = (
            session.query(StatusCheck)
            .filter(StatusCheck.service_id == service_id, StatusCheck.checked_at >= cutoff)
            .count()
        )
        operational = (
            session.query(StatusCheck)
            .filter(
                StatusCheck.service_id == service_id,
                StatusCheck.checked_at >= cutoff,
                StatusCheck.status == "operational",
            )
            .count()
        )

    uptime_pct = round(operational / total * 100, 2) if total > 0 else 0.0
    return UptimeResponse(
        service_id=service_id,
        hours=hours,
        total_checks=total,
        operational_checks=operational,
        uptime_percent=uptime_pct,
    )


@app.get("/services/{service_id}/history", response_model=HistoryResponse)
def get_history(service_id: str, limit: int = 60):
    limit = min(limit, 500)  # cap to prevent runaway queries
    with get_session() as session:
        if not session.get(ServiceRow, service_id):
            raise HTTPException(status_code=404, detail="Service not found")

        rows = (
            session.query(StatusCheck)
            .filter(StatusCheck.service_id == service_id)
            .order_by(StatusCheck.checked_at.desc())
            .limit(limit)
            .all()
        )

        # compute avg over non-null response_ms values in this result set
        ms_values = [r.response_ms for r in rows if r.response_ms is not None]
        avg_ms = round(sum(ms_values) / len(ms_values)) if ms_values else None
        latest_ms = rows[0].response_ms if rows else None

        def fmt_dt(dt: datetime) -> str:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()

        checks = [
            CheckEntry(
                status=r.status,
                response_ms=r.response_ms,
                detail=r.detail,
                checked_at=fmt_dt(r.checked_at),
            )
            for r in rows
        ]

    return HistoryResponse(
        service_id=service_id,
        count=len(checks),
        avg_response_ms=avg_ms,
        latest_response_ms=latest_ms,
        checks=checks,
    )


@app.get("/cache/stats", response_model=CacheStatsResponse)
def cache_stats():
    # read hit/miss counters from Redis; default to 0 if key missing or Redis is down
    try:
        hits = int(redis_client.get("cache:hits") or 0)
        misses = int(redis_client.get("cache:misses") or 0)
    except redis.RedisError as exc:
        print(f"[cache] WARNING: Redis unavailable ({exc}), returning zeroed stats")
        hits, misses = 0, 0

    total = hits + misses
    hit_rate = round(hits / total * 100, 2) if total > 0 else 0.0
    return CacheStatsResponse(hits=hits, misses=misses, total=total, hit_rate_percent=hit_rate)


class WebhookPayload(BaseModel):
    service_id: str
    status: StatusEnum


@app.post("/webhook/status", status_code=201)
def receive_webhook(payload: WebhookPayload):
    now = datetime.now(timezone.utc)
    with get_session() as session:
        row = session.get(ServiceRow, payload.service_id)
        if not row:
            row = ServiceRow(
                id=payload.service_id,
                name=payload.service_id.title(),
                status=payload.status,
                last_updated=now,
            )
            session.add(row)
        else:
            row.status = payload.status
            row.last_updated = now

        # response_ms is null for manual webhook updates (no HTTP round-trip)
        session.add(StatusCheck(
            service_id=payload.service_id,
            status=payload.status,
            response_ms=None,
            detail="Manual webhook update",
            checked_at=now,
        ))

    cache_delete(CACHE_KEY_SERVICES)
    return {"received": True, "service_id": payload.service_id, "status": payload.status}
