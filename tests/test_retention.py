from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.pool import QueuePool

import backend.app.services.retention as retention
from backend.app.models import Audit, Conversation, Evidence, Lead, Message, MessageEvent, utc_now


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class _Connection:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.parameters = []
        self.invalidated = False
        self.detached = False
        self.returned_to_pool = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.returned_to_pool = True
        return False

    @property
    def reusable(self):
        return self.returned_to_pool and not self.invalidated and not self.detached

    def execute(self, _statement, parameters):
        self.parameters.append(parameters)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return _Result(outcome)

    def invalidate(self, _exception=None):
        self.invalidated = True

    def detach(self):
        self.detached = True


class _Engine:
    def __init__(self, connection):
        self.connection = connection

    def connect(self):
        return self.connection


class _Session:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def commit(self):
        pass


def _patch_postgres_cleanup(monkeypatch, connection, cleanup):
    monkeypatch.setattr(retention, "engine", _Engine(connection))
    monkeypatch.setattr(retention, "SessionLocal", lambda **_kwargs: _Session())
    monkeypatch.setattr(retention, "purge_expired_message_content", cleanup)


def test_retention_cleanup_acquires_and_releases_postgres_lock(monkeypatch):
    connection = _Connection([True, True])
    _patch_postgres_cleanup(monkeypatch, connection, lambda _db: 4)

    assert retention.purge_expired_content() == 4
    assert connection.parameters == [
        {"lock_key": retention.RETENTION_CLEANUP_LOCK_KEY},
        {"lock_key": retention.RETENTION_CLEANUP_LOCK_KEY},
    ]
    assert not connection.invalidated
    assert connection.reusable


def test_retention_cleanup_skips_when_postgres_lock_is_unavailable(monkeypatch):
    connection = _Connection([False])

    def unexpected_session(**_kwargs):
        raise AssertionError("Cleanup must not run without the distributed lock.")

    monkeypatch.setattr(retention, "engine", _Engine(connection))
    monkeypatch.setattr(retention, "SessionLocal", unexpected_session)

    assert retention.purge_expired_content() == 0
    assert connection.parameters == [{"lock_key": retention.RETENTION_CLEANUP_LOCK_KEY}]
    assert connection.reusable


def test_retention_cleanup_releases_lock_after_cleanup_failure(monkeypatch):
    connection = _Connection([True, True])

    def fail_cleanup(_db):
        raise RuntimeError("synthetic cleanup failure")

    _patch_postgres_cleanup(monkeypatch, connection, fail_cleanup)

    with pytest.raises(RuntimeError, match="synthetic cleanup failure"):
        retention.purge_expired_content()

    assert len(connection.parameters) == 2
    assert connection.reusable


def test_retention_cleanup_invalidates_connection_when_unlock_raises(monkeypatch):
    connection = _Connection([True, RuntimeError("synthetic unlock failure")])
    _patch_postgres_cleanup(monkeypatch, connection, lambda _db: 1)

    with pytest.raises(
        retention.RetentionLockReleaseError,
        match="Could not confirm PostgreSQL advisory lock release",
    ) as captured:
        retention.purge_expired_content()

    assert str(captured.value.__cause__) == "synthetic unlock failure"
    assert connection.invalidated
    assert not connection.reusable


def test_retention_cleanup_invalidates_connection_when_unlock_is_unconfirmed(
    monkeypatch,
):
    connection = _Connection([True, False])
    _patch_postgres_cleanup(monkeypatch, connection, lambda _db: 1)

    with pytest.raises(
        retention.RetentionLockReleaseError,
        match="did not confirm advisory lock release",
    ):
        retention.purge_expired_content()

    assert connection.invalidated
    assert not connection.reusable


def test_retention_cleanup_detaches_connection_if_invalidation_fails(monkeypatch):
    class InvalidationFailureConnection(_Connection):
        def invalidate(self, _exception=None):
            raise RuntimeError("synthetic invalidation failure")

    connection = InvalidationFailureConnection(
        [True, RuntimeError("synthetic unlock failure")]
    )
    _patch_postgres_cleanup(monkeypatch, connection, lambda _db: 1)

    with pytest.raises(ExceptionGroup) as captured:
        retention.purge_expired_content()

    assert [str(error) for error in captured.value.exceptions] == [
        "synthetic unlock failure",
        "synthetic invalidation failure",
    ]
    assert connection.detached
    assert not connection.reusable


def test_retention_cleanup_reports_both_cleanup_and_unlock_errors(monkeypatch):
    connection = _Connection([True, RuntimeError("synthetic unlock failure")])

    def fail_cleanup(_db):
        raise ValueError("synthetic cleanup failure")

    _patch_postgres_cleanup(monkeypatch, connection, fail_cleanup)

    with pytest.raises(ExceptionGroup) as captured:
        retention.purge_expired_content()

    assert [str(error) for error in captured.value.exceptions] == [
        "synthetic cleanup failure",
        "Could not confirm PostgreSQL advisory lock release.",
    ]
    assert str(captured.value.exceptions[1].__cause__) == "synthetic unlock failure"
    assert connection.invalidated
    assert not connection.reusable


def test_retention_cleanup_invalidates_connection_if_lock_acquisition_raises(
    monkeypatch,
):
    connection = _Connection([RuntimeError("synthetic acquisition failure")])

    def unexpected_session(**_kwargs):
        raise AssertionError("Cleanup must not run when acquisition is ambiguous.")

    monkeypatch.setattr(retention, "engine", _Engine(connection))
    monkeypatch.setattr(retention, "SessionLocal", unexpected_session)

    with pytest.raises(
        retention.RetentionLockAcquisitionError,
        match="Could not confirm PostgreSQL advisory lock acquisition",
    ) as captured:
        retention.purge_expired_content()

    assert str(captured.value.__cause__) == "synthetic acquisition failure"
    assert connection.invalidated
    assert not connection.reusable


class _PooledPostgresConnection:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self, connection, fail_invalidation=False):
        self.connection = connection
        self.executions = 0
        self.invalidation_requested = False
        self.fail_invalidation = fail_invalidation
        self.detached = False

    @property
    def invalidated(self):
        return self.invalidation_requested or self.connection.invalidated

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return self.connection.__exit__(*args)

    def execute(self, _statement, _parameters):
        self.executions += 1
        self.connection.execute(text("SELECT 1"))
        if self.executions == 1:
            return _Result(True)
        raise RuntimeError("synthetic unlock failure")

    def invalidate(self, exception=None):
        if self.fail_invalidation:
            raise RuntimeError("synthetic invalidation failure")
        self.invalidation_requested = True
        self.connection.invalidate(exception)

    def detach(self):
        self.detached = True
        self.connection.detach()


class _PooledEngine:
    def __init__(self, engine, fail_invalidation=False):
        self.engine = engine
        self.checked_out = []
        self.fail_invalidation = fail_invalidation

    def connect(self):
        connection = _PooledPostgresConnection(
            self.engine.connect(), fail_invalidation=self.fail_invalidation
        )
        self.checked_out.append(connection)
        return connection


@pytest.mark.parametrize(
    ("fail_invalidation", "expected_error"),
    [
        (False, retention.RetentionLockReleaseError),
        (True, ExceptionGroup),
    ],
)
def test_unconfirmed_unlock_discards_physical_connection_from_sqlalchemy_pool(
    monkeypatch, tmp_path, fail_invalidation, expected_error
):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'retention-pool.sqlite'}",
        poolclass=QueuePool,
        pool_size=1,
        max_overflow=0,
    )
    created_connections = []
    invalidations = []
    event.listen(engine, "connect", lambda dbapi, _record: created_connections.append(dbapi))
    event.listen(
        engine,
        "invalidate",
        lambda _dbapi, _record, _exception: invalidations.append(True),
    )
    pool_proxy = _PooledEngine(engine, fail_invalidation=fail_invalidation)
    monkeypatch.setattr(retention, "engine", pool_proxy)
    monkeypatch.setattr(retention, "SessionLocal", lambda **_kwargs: _Session())
    monkeypatch.setattr(retention, "purge_expired_message_content", lambda _db: 1)

    try:
        with pytest.raises(expected_error):
            retention.purge_expired_content()

        if fail_invalidation:
            assert pool_proxy.checked_out[0].detached
            assert invalidations == []
        else:
            assert pool_proxy.checked_out[0].invalidated
            assert invalidations == [True]

        with engine.connect() as connection:
            replacement = connection.connection.driver_connection
            assert replacement is not created_connections[0]
    finally:
        engine.dispose()


def test_sqlite_retention_wrapper_preserves_audits_and_records_expiry_event(
    db_session_factory, monkeypatch
):
    with db_session_factory() as db:
        engine = db.get_bind()
        lead = Lead(tenant_id="synthetic-tenant", classification="lost")
        db.add(lead)
        db.flush()
        conversation = Conversation(
            lead_id=lead.id,
            channel="synthetic",
            capture_source="test fixture",
        )
        db.add(conversation)
        db.flush()
        message = Message(
            conversation_id=conversation.id,
            direction="inbound",
            body="Synthetic expired content.",
            authorized_for_audit=True,
            retention_until=utc_now() - timedelta(seconds=1),
        )
        audit = Audit(lead_id=lead.id, original_reason="Synthetic audit reason")
        db.add_all([message, audit])
        db.flush()
        evidence = Evidence(
            audit_id=audit.id,
            message_id=message.id,
            source_type="message",
            excerpt="Synthetic evidence excerpt.",
            verified=True,
        )
        db.add(evidence)
        db.commit()
        message_id, audit_id, evidence_id = message.id, audit.id, evidence.id

    monkeypatch.setattr(retention, "engine", engine)
    monkeypatch.setattr(retention, "SessionLocal", db_session_factory)

    assert retention.purge_expired_content() == 1

    with db_session_factory() as db:
        message = db.get(Message, message_id)
        assert message is not None
        assert message.body == ""
        assert message.deleted_at is not None
        assert db.get(Audit, audit_id) is not None
        retained_evidence = db.get(Evidence, evidence_id)
        assert retained_evidence is not None
        assert retained_evidence.excerpt == ""
        assert not retained_evidence.verified
        assert db.scalar(
            select(MessageEvent).where(
                MessageEvent.message_id == message_id,
                MessageEvent.event_type == "retention_expired",
            )
        ) is not None
