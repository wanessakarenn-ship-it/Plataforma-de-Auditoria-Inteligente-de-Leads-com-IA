import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

import firebase_admin
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.exceptions import DefaultCredentialsError
from firebase_admin import auth as firebase_auth
from firebase_admin import exceptions as firebase_exceptions
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.db import get_db
from backend.app.models import AdminActionLog

logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)
Role = Literal["admin", "auditor", "gestor"]


@dataclass(frozen=True)
class Principal:
    uid: str
    role: Role
    tenant_id: str
    additional_roles: frozenset[Role] = frozenset()


@lru_cache(maxsize=4)
def _firebase_app(project_id: str):
    name = f"bc-lead-intelligence-{project_id}"
    try:
        app = firebase_admin.get_app(name)
    except ValueError:
        app = firebase_admin.initialize_app(options={"projectId": project_id}, name=name)
    if app.project_id != project_id:
        raise RuntimeError("Firebase Admin app project does not match configured project.")
    return app


def verify_firebase_id_token(token: str, project_id: str) -> dict:
    app = _firebase_app(project_id)
    return firebase_auth.verify_id_token(token, app=app, check_revoked=True)


def get_firebase_admin_app():
    settings = get_settings()
    project_id = settings.firebase_project_id.strip()
    if not project_id or project_id != settings.google_cloud_project:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase authentication is not configured for the verified project.",
        )
    try:
        return _firebase_app(project_id)
    except (DefaultCredentialsError, ValueError, RuntimeError) as exc:
        logger.error("Firebase Admin SDK initialization failed (%s).", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase authentication is unavailable.",
        ) from exc


async def get_current_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> Principal:
    settings = get_settings()
    firebase_project_id = settings.firebase_project_id.strip()
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not firebase_project_id or firebase_project_id != settings.google_cloud_project:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase authentication is not configured for the verified project.",
        )
    try:
        claims = verify_firebase_id_token(credentials.credentials, firebase_project_id)
    except (
        firebase_auth.InvalidIdTokenError,
        firebase_auth.ExpiredIdTokenError,
        firebase_auth.RevokedIdTokenError,
        firebase_auth.UserDisabledError,
        ValueError,
    ) as exc:
        logger.info("Firebase ID token verification failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except firebase_auth.CertificateFetchError as exc:
        logger.error("Firebase certificate verification is unavailable.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase token verification is temporarily unavailable.",
        ) from exc
    except firebase_exceptions.FirebaseError as exc:
        logger.error("Firebase token verification service failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase token verification is temporarily unavailable.",
        ) from exc
    except (DefaultCredentialsError, RuntimeError) as exc:
        logger.error("Firebase Admin credentials or project configuration are unavailable.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase token verification is temporarily unavailable.",
        ) from exc

    uid = claims.get("uid") or claims.get("sub")
    role = claims.get("role")
    tenant_id = claims.get("tenant_id")
    if (
        not isinstance(uid, str)
        or not uid
        or not isinstance(role, str)
        or role not in {"admin", "auditor", "gestor"}
        or not isinstance(tenant_id, str)
        or not tenant_id.strip()
        or tenant_id != tenant_id.strip()
        or len(tenant_id) > 128
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The authenticated account has no valid application role or organization.",
        )
    principal = Principal(uid=uid, role=role, tenant_id=tenant_id)
    request.state.principal = principal
    return principal


def require_roles(*allowed_roles: Role):
    async def authorize(
        request: Request,
        principal: Principal = Depends(get_current_principal),
        db: Session = Depends(get_db),
    ) -> Principal:
        if principal.role not in allowed_roles and not principal.additional_roles.intersection(
            allowed_roles
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role for this operation.",
            )
        request.state.principal = principal
        if request.method not in {"GET", "HEAD", "OPTIONS"} or "admin" in allowed_roles:
            route = request.scope.get("route")
            route_template = getattr(route, "path", "/unknown")
            resource_id = next(
                (
                    value
                    for key, value in request.path_params.items()
                    if key in {"lead_id", "audit_id", "import_id", "uid"}
                ),
                None,
            )
            action = AdminActionLog(
                actor_uid=principal.uid,
                actor_role=principal.role,
                tenant_id=principal.tenant_id,
                method=request.method,
                route=route_template[:240],
                resource_id=str(resource_id)[:160] if resource_id else None,
            )
            db.add(action)
            try:
                db.commit()
            except SQLAlchemyError as exc:
                db.rollback()
                logger.error(
                    "Could not persist authorized API action (%s).",
                    type(exc).__name__,
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Administrative action logging is unavailable.",
                )
            request.state.admin_action_log_id = action.id
            request.state.admin_action_bind = db.get_bind()
        return principal

    return authorize
