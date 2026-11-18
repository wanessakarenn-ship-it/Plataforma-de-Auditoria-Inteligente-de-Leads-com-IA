from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes import router
from backend.app.config import get_settings
from backend.app.services.vertex_audit import VertexAuditNotConfigured

settings = get_settings()
app = FastAPI(title="BC Lead Intelligence API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.api_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.include_router(router, prefix="/api")

__all__ = ["app", "VertexAuditNotConfigured"]
