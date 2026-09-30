import os
from datetime import datetime
from threading import Lock
from time import monotonic
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator, model_validator

MAX_REQUEST_BYTES = int(os.getenv("MAX_REQUEST_BYTES", "65536"))
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "60"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))

# Local-only by default. Set ALLOW_REMOTE=true only when the deployment explicitly
# needs network access and the surrounding infrastructure provides authentication.
ALLOW_REMOTE = os.getenv("ALLOW_REMOTE", "false").lower() == "true"
HOST = os.getenv("HOST", "127.0.0.1")
if not ALLOW_REMOTE:
    HOST = "127.0.0.1"

CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin.strip()]
if not CORS_ORIGINS:
    CORS_ORIGINS = ["http://127.0.0.1:5173", "http://localhost:5173"]

app = FastAPI(title="grimreaperX API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)

class UsageEvent(BaseModel):
    id: UUID
    device_id: str = Field(min_length=1, max_length=128)
    app_name: str = Field(min_length=1, max_length=256)
    category: str = Field(min_length=1, max_length=128)
    start_ts: datetime
    end_ts: datetime

    @field_validator("device_id", "app_name", "category")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value.strip()

    @field_validator("start_ts", "end_ts")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include timezone information")
        return value

    @model_validator(mode="after")
    def validate_interval(self):
        if self.end_ts < self.start_ts:
            raise ValueError("end_ts must be greater than or equal to start_ts")
        return self


_rate_lock = Lock()
_rate_buckets: dict[str, list[float]] = {}


def check_rate_limit(identity: str) -> tuple[bool, int]:
    now = monotonic()
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS
    with _rate_lock:
        timestamps = [ts for ts in _rate_buckets.get(identity, []) if ts > cutoff]
        if len(timestamps) >= RATE_LIMIT_REQUESTS:
            retry_after = max(1, int(timestamps[0] + RATE_LIMIT_WINDOW_SECONDS - now))
            _rate_buckets[identity] = timestamps
            return False, retry_after
        timestamps.append(now)
        _rate_buckets[identity] = timestamps
    return True, 0


@app.middleware("http")
async def request_size_limit(request: Request, call_next):
    body = await request.body()
    if len(body) > MAX_REQUEST_BYTES:
        return JSONResponse(status_code=413, content={"detail": "request body too large"})
    return await call_next(request)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/v1/usage-events", status_code=202)
async def ingest_usage(event: UsageEvent, request: Request):
    identity = event.device_id or (request.client.host if request.client else "unknown")
    allowed, retry_after = check_rate_limit(identity)
    if not allowed:
        return JSONResponse(
            status_code=429,
            content={"detail": "rate limit exceeded"},
            headers={"Retry-After": str(retry_after)},
        )
    return {"accepted": True, "event_id": str(event.id)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=int(os.getenv("PORT", "8000")), reload=True)
