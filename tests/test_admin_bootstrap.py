from types import SimpleNamespace

import pytest

from backend.scripts import bootstrap_admin


def test_bootstrap_assigns_first_admin_for_tenant_without_overwriting_other_claims(
    monkeypatch,
):
    observed = {}
    app = object()
    target_user = SimpleNamespace(custom_claims={"locale": "pt-BR"})
    pages = [
        SimpleNamespace(
            users=[
                SimpleNamespace(custom_claims={"role": "admin", "tenant_id": "other-tenant"})
            ],
            next_page_token=None,
        )
    ]
    monkeypatch.setattr(bootstrap_admin, "_firebase_app_for_project", lambda: app)
    monkeypatch.setattr(
        bootstrap_admin.firebase_auth,
        "list_users",
        lambda **kwargs: pages.pop(0),
    )
    monkeypatch.setattr(
        bootstrap_admin.firebase_auth,
        "get_user",
        lambda uid, **kwargs: target_user,
    )
    monkeypatch.setattr(
        bootstrap_admin.firebase_auth,
        "set_custom_user_claims",
        lambda uid, claims, **kwargs: observed.update(uid=uid, claims=claims),
    )

    bootstrap_admin.bootstrap_first_admin("synthetic-uid", "tenant-a")

    assert observed == {
        "uid": "synthetic-uid",
        "claims": {"locale": "pt-BR", "role": "admin", "tenant_id": "tenant-a"},
    }


def test_bootstrap_refuses_existing_or_unscoped_admin(monkeypatch):
    monkeypatch.setattr(bootstrap_admin, "_firebase_app_for_project", object)
    monkeypatch.setattr(
        bootstrap_admin.firebase_auth,
        "list_users",
        lambda **kwargs: SimpleNamespace(
            users=[SimpleNamespace(custom_claims={"role": "admin", "tenant_id": "tenant-a"})],
            next_page_token=None,
        ),
    )

    with pytest.raises(RuntimeError, match="manual review"):
        bootstrap_admin.bootstrap_first_admin("synthetic-uid", "tenant-a")


def test_bootstrap_refuses_accounts_with_existing_access_claims(monkeypatch):
    monkeypatch.setattr(bootstrap_admin, "_firebase_app_for_project", object)
    monkeypatch.setattr(
        bootstrap_admin.firebase_auth,
        "list_users",
        lambda **kwargs: SimpleNamespace(users=[], next_page_token=None),
    )
    monkeypatch.setattr(
        bootstrap_admin.firebase_auth,
        "get_user",
        lambda uid, **kwargs: SimpleNamespace(custom_claims={"tenant_id": "tenant-a"}),
    )

    with pytest.raises(RuntimeError, match="already has access claims"):
        bootstrap_admin.bootstrap_first_admin("synthetic-uid", "tenant-a")


@pytest.mark.parametrize(
    ("firebase_project_id", "google_cloud_project"),
    [
        ("unexpected-project", "prime-amulet-439718-e3"),
        ("prime-amulet-439718-e3", "unexpected-project"),
    ],
)
def test_bootstrap_refuses_unverified_project_configuration(
    monkeypatch, firebase_project_id, google_cloud_project
):
    monkeypatch.setattr(
        bootstrap_admin,
        "get_settings",
        lambda: SimpleNamespace(
            firebase_project_id=firebase_project_id,
            google_cloud_project=google_cloud_project,
        ),
    )
    firebase_app_calls = []
    monkeypatch.setattr(
        bootstrap_admin,
        "get_firebase_admin_app",
        lambda: firebase_app_calls.append("called"),
    )

    with pytest.raises(RuntimeError, match="verified Firebase project"):
        bootstrap_admin._firebase_app_for_project()
    assert firebase_app_calls == []


def test_bootstrap_refuses_admin_app_for_a_different_project(monkeypatch):
    monkeypatch.setattr(
        bootstrap_admin,
        "get_settings",
        lambda: SimpleNamespace(
            firebase_project_id="prime-amulet-439718-e3",
            google_cloud_project="prime-amulet-439718-e3",
        ),
    )
    monkeypatch.setattr(
        bootstrap_admin,
        "get_firebase_admin_app",
        lambda: SimpleNamespace(project_id="unexpected-project"),
    )

    with pytest.raises(RuntimeError, match="unexpected project"):
        bootstrap_admin._firebase_app_for_project()
