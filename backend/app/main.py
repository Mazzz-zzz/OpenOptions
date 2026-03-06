from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings
from app.routers import alerts, contracts, fetch, iv_analysis, surface, underlyings

settings = get_settings()

app = FastAPI(
    title="OpenOptions — Mispricing Tracker",
    version="1.0.0",
)


class IPWhitelistMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        allowed = settings.allowed_ips
        if not allowed:
            return await call_next(request)
        # API Gateway sets X-Forwarded-For: <client>, <proxy>...
        forwarded = request.headers.get("x-forwarded-for", "")
        client_ip = forwarded.split(",")[0].strip() if forwarded else ""
        if not client_ip and request.client:
            client_ip = request.client.host
        if client_ip not in allowed:
            return JSONResponse(status_code=403, content={"detail": "Forbidden"})
        return await call_next(request)


app.add_middleware(IPWhitelistMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(fetch.router, prefix="/api", tags=["fetch"])
app.include_router(alerts.router, prefix="/api", tags=["alerts"])
app.include_router(contracts.router, prefix="/api", tags=["contracts"])
app.include_router(surface.router, prefix="/api", tags=["surface"])
app.include_router(iv_analysis.router, prefix="/api", tags=["iv-analysis"])
app.include_router(underlyings.router, prefix="/api", tags=["underlyings"])


@app.get("/health")
async def health():
    return {"status": "ok"}
