import os
import threading

from config.turso_backend.base import DatabaseWrapper


def _wrapper(name, **options):
    return DatabaseWrapper({"NAME": name, "OPTIONS": options, "ENGINE": "config.turso_backend",
                            "TIME_ZONE": None, "CONN_MAX_AGE": 0, "CONN_HEALTH_CHECKS": False,
                            "AUTOCOMMIT": True, "ATOMIC_REQUESTS": False, "TEST": {}}, alias="default")


def test_remote_mode_connects_to_the_url():
    db = _wrapper("libsql://example.turso.io", auth_token="t")
    params = db.get_connection_params()
    assert params["database"] == "libsql://example.turso.io" and params["auth_token"] == "t"
    assert db.is_remote and not db.is_replica and "sync_url" not in params


def test_replica_mode_uses_a_local_file_per_process_and_thread(tmp_path):
    db = _wrapper("libsql://example.turso.io", auth_token="t", replica_dir=str(tmp_path / "replicas"))
    params = db.get_connection_params()
    assert params["sync_url"] == "libsql://example.turso.io"
    assert params["database"] == str(tmp_path / "replicas" / f"default-{os.getpid()}-{threading.get_ident()}.db")
    assert "replica_dir" not in params and (tmp_path / "replicas").is_dir()
    assert db.is_replica and db.is_remote


def test_local_file_is_neither_remote_nor_replica(tmp_path):
    db = _wrapper(str(tmp_path / "local.db"), replica_dir="")
    assert not db.is_remote and not db.is_replica
    assert "sync_url" not in db.get_connection_params()


class _FakeDriver:
    """Stands in for a libsql replica connection: counts syncs, accepts any statement."""

    def __init__(self):
        self.syncs = 0

    def sync(self):
        self.syncs += 1

    def cursor(self):
        return self

    def execute(self, *args):
        return self

    def commit(self):
        pass


def test_replica_syncs_only_after_a_write_or_on_its_timer(tmp_path, monkeypatch):
    from config.turso_backend import base

    worker_a = _wrapper("libsql://example.turso.io", replica_dir=str(tmp_path))
    worker_b = _wrapper("libsql://example.turso.io", replica_dir=str(tmp_path))
    for db in (worker_a, worker_b):
        db.connection = base.Connection(_FakeDriver(), db.mark_write)
        db._sync(db.connection)
    b = worker_b.connection.connection

    worker_b.sync_replica()  # nothing written anywhere: no round trip
    worker_a.connection.execute("SELECT 1")
    worker_b.sync_replica()
    assert b.syncs == 1

    worker_a.connection.execute("UPDATE t SET x = 1")  # another worker wrote: sync once
    worker_b.sync_replica()
    assert b.syncs == 2
    old = worker_b._synced_ns - 10**9  # as if B's sync were a second after the write
    os.utime(worker_a.write_marker, ns=(old, old))
    worker_b.sync_replica()
    assert b.syncs == 2

    worker_a.connection.commit()
    worker_b.sync_replica()
    assert b.syncs == 3

    now = base.time.monotonic()
    monkeypatch.setattr(base.time, "monotonic", lambda: now + base.SYNC_EVERY)  # writes from elsewhere
    worker_b.sync_replica()
    assert b.syncs == 4
