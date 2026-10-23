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
