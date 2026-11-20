import sys

from fastapi import HTTPException
from firebase_admin import auth as firebase_auth
from firebase_admin import exceptions as firebase_exceptions

from backend.app.auth import get_firebase_admin_app
from backend.app.config import get_settings

EXPECTED_FIREBASE_PROJECT_ID = "prime-amulet-439718-e3"


def _configured_project_id() -> str:
    settings = get_settings()
    firebase_project_id = settings.firebase_project_id.strip()
    google_cloud_project = settings.google_cloud_project.strip()
    if (
        firebase_project_id != EXPECTED_FIREBASE_PROJECT_ID
        or google_cloud_project != EXPECTED_FIREBASE_PROJECT_ID
    ):
        raise RuntimeError("Configure both project IDs to the verified Firebase project.")
    return firebase_project_id


def _firebase_app_for_project():
    project_id = _configured_project_id()
    app = get_firebase_admin_app()
    if app.project_id != project_id:
        raise RuntimeError("Firebase Admin SDK initialized for an unexpected project.")
    return app


def bootstrap_first_admin(uid: str, tenant_id: str) -> None:
    if not uid or uid != uid.strip() or len(uid) > 128:
        raise ValueError("Provide a valid Firebase Authentication UID.")
    if not tenant_id or tenant_id != tenant_id.strip() or len(tenant_id) > 128:
        raise ValueError("Provide a valid organization tenant ID.")

    app = _firebase_app_for_project()
    page_token = None
    try:
        while True:
            page = firebase_auth.list_users(
                app=app,
                max_results=1000,
                page_token=page_token,
            )
            for user in page.users:
                claims = user.custom_claims or {}
                if claims.get("role") == "admin":
                    existing_tenant = claims.get("tenant_id")
                    if not existing_tenant or existing_tenant == tenant_id:
                        raise RuntimeError(
                            "An existing or unscoped administrator requires manual review."
                        )
            page_token = page.next_page_token
            if not page_token:
                break

        user = firebase_auth.get_user(uid, app=app)
        claims = dict(user.custom_claims or {})
        if "role" in claims or "tenant_id" in claims:
            raise RuntimeError(
                "The selected account already has access claims; use the approved admin process."
            )
        claims.update(role="admin", tenant_id=tenant_id)
        firebase_auth.set_custom_user_claims(uid, claims, app=app)
    except firebase_exceptions.FirebaseError as exc:
        raise RuntimeError(
            "Firebase Admin operation failed; verify ADC, project configuration, and IAM."
        ) from exc


def main() -> None:
    if not sys.stdin.isatty():
        raise SystemExit("Run this one-time bootstrap interactively.")

    try:
        project_id = _configured_project_id()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

    print("This assigns claims to an existing Firebase Authentication account.")
    print("It does not create an account, organization, or authentication bypass.")
    uid = input("Firebase Authentication UID: ").strip()
    tenant_id = input("Organization tenant ID: ").strip()
    if input("Re-enter the Firebase Authentication UID to confirm: ").strip() != uid:
        raise SystemExit("UID confirmation did not match; no changes were made.")
    if input("Re-enter the organization tenant ID to confirm: ").strip() != tenant_id:
        raise SystemExit("Tenant ID confirmation did not match; no changes were made.")
    if input(f"Type {project_id} to confirm the Firebase project: ").strip() != project_id:
        raise SystemExit("Project confirmation did not match; no changes were made.")

    try:
        bootstrap_first_admin(uid, tenant_id)
    except HTTPException as exc:
        raise SystemExit(f"Firebase Admin is unavailable: {exc.detail}") from exc
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    print("Administrator claims assigned. Sign in again to refresh the Firebase ID token.")


if __name__ == "__main__":
    main()
