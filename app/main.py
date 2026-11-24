from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .config import settings
from .database import init_db
from .ratelimit import limiter
from .routers import auth, claims, complaints


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()          # create tables + seed the two demo policy holders
    yield


app = FastAPI(title="ClaimSaathi API", version="1.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(auth.router)
app.include_router(complaints.router)
app.include_router(claims.router)


@app.get("/health")
def health():
    return {"status": "ok", "demo_mode": settings.demo_mode, "ai_enabled": settings.ai_enabled}