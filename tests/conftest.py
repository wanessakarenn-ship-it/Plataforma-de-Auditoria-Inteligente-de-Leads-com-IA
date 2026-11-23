import os

os.environ.update(
    {
        "APP_ENV": "test",
        "CLOUD_SQL_IAM_AUTH": "false",
        "DATABASE_URL": "sqlite://",
        "VERTEX_AI_ENABLED": "false",
        "VERTEX_AI_APPROVED": "false",
    }
)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.auth import Principal, get_current_principal
from backend.app.db import get_db
from backend.app.main import app
from backend.app.models import Base


@pytest.fixture
def db_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    def override_get_db():
        with TestingSession() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        uid="synthetic-test-user",
        role="auditor",
        tenant_id="test-tenant",
        additional_roles=frozenset({"admin", "gestor"}),
    )
    yield TestingSession
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(db_session_factory):
    with TestClient(app) as test_client:
        yield test_client
