import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as SQLAlchemySession

from backend.app.db import close_database_resources
from backend.app.api.audits import router as audit_router
from backend.app.api.karen import router as karen_router
from backend.app.api.knowledge import router as knowledge_router
from backend.app.api.studio import router as studio_router
from backend.app.api.routes import router
from backend.app.config import (
    CLOUD_SQL_API_RUNTIME_IDENTITY,
    get_settings,
    require_cloud_sql_identity,
)
from backend.app.models import AdminActionLog
from backend.app.services.vertex_audit import VertexAuditNotConfigured
from backend.app.services.retention import retention_cleanup_loop

logger = logging.getLogger(__name__)
settings = get_settings()
require_cloud_sql_identity(settings, CLOUD_SQL_API_RUNTIME_IDENTITY)


@asynccontextmanager
async def lifespan(_: FastAPI):
    cleanup_task = (
        None
        if settings.app_env.strip().lower() == "test"
        else asyncio.create_task(retention_cleanup_loop())
    )
    try:
        yield
    finally:
        if cleanup_task is not None:
            cleanup_task.cancel()
            with suppress(asyncio.CancelledError):
                await cleanup_task
        close_database_resources()


app = FastAPI(title="Lead Intelligence AI API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.api_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def finalize_authorized_action_log(request, call_next):
    response = await call_next(request)
    action_id = getattr(request.state, "admin_action_log_id", None)
    bind = getattr(request.state, "admin_action_bind", None)
    if action_id and bind is not None:
        try:
            with SQLAlchemySession(bind=bind) as db:
                action = db.get(AdminActionLog, action_id)
                if action is not None:
                    action.status_code = response.status_code
                    action.outcome = "succeeded" if response.status_code < 400 else "failed"
                    db.commit()
        except SQLAlchemyError as exc:
            logger.error(
                "Could not finalize authorized API action log (%s).",
                type(exc).__name__,
            )
    return response


app.include_router(router, prefix="/api")
app.include_router(audit_router, prefix="/api")
app.include_router(studio_router, prefix="/api")
app.include_router(karen_router, prefix="/api")
app.include_router(knowledge_router, prefix="/api")

__all__ = ["app", "VertexAuditNotConfigured"]
